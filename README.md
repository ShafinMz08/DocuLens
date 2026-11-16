# DocuLens

DocuLens is an AI-powered document intelligence platform that enables intelligent document processing, analysis, and retrieval.

## Features

- Document upload, text extraction, and chunking
- Local CPU embeddings via FastEmbed (`BAAI/bge-small-en-v1.5`, 384 dimensions, pgvector)
- Semantic search over document chunks with cosine similarity
- Document-grounded question answering with source citations
- Persistent conversations with follow-up questions
- Gemini primary LLM with Groq fallback (official SDKs, no keys required for tests)
- Scalable architecture with FastAPI, PostgreSQL + pgvector, and Redis

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Python 3.12+ (for local development)

### Running with Docker Compose

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Update the `.env` file with your secure passwords and configuration.

3. Start the services:
   ```bash
   docker-compose up --build
   ```

4. The backend API will be available at `http://localhost:8002`

5. Check the health endpoint:
   ```bash
   curl http://localhost:8002/health
   ```

   Expected response:
   ```json
   {"status": "ok"}
   ```

## Project Structure

```
DocuLens/
├── backend/           # FastAPI backend application
│   ├── app/
│   │   ├── api/       # API routes
│   │   ├── core/      # Configuration and logging
│   │   ├── db/        # Database session and models
│   │   ├── models/    # SQLAlchemy models
│   │   ├── schemas/   # Pydantic schemas
│   │   └── services/  # Business logic
│   ├── tests/         # Test files
│   └── alembic/       # Database migrations
├── frontend/          # Frontend application (placeholder)
└── docker-compose.yml # Docker services configuration
```

## Development

### Backend Development

The backend uses FastAPI with async PostgreSQL and Redis. Database migrations are managed with Alembic.

To run migrations:
```bash
docker-compose exec backend alembic upgrade head
```

To migrate the test database instead:

```bash
docker-compose exec -e USE_TEST_DATABASE=1 backend alembic upgrade head
```

The first `docker compose up` builds a custom PostgreSQL 16 Alpine image
(`docker/postgres/Dockerfile`) that compiles pgvector v0.8.1 from source —
Alpine's `postgresql-pgvector` package is not compatible with the official
Postgres image. The `vector` extension is enabled by an Alembic migration.

To run tests:
```bash
docker-compose exec backend pytest
```

## Embeddings & Semantic Search (Phase 3)

DocuLens generates embeddings locally on CPU using
[FastEmbed](https://github.com/qdrant/fastembed) with the
`BAAI/bge-small-en-v1.5` model (384 dimensions). No external API keys are
required. The model is downloaded once on first use (~100 MB) and cached in
`./storage/fastembed` (mounted into the backend container).

### Embedding a document

A document must be processed first (`POST /api/v1/documents/{id}/process`).
Then trigger embedding:

```bash
curl -X POST http://localhost:8002/api/v1/documents/{document_id}/embed
```

The response reports `total_chunks`, `embedded_chunks`, `skipped_chunks`
(blank chunks), and the `embedding_model` key (e.g.
`BAAI/bge-small-en-v1.5@1`). Repeating the request is safe: chunks that
already carry the current model's embeddings are skipped. If embedding
fails, the document's `embedding_status` becomes `failed` with an error
message; retrying the endpoint resumes only the missing/stale chunks.

### Semantic search

```bash
curl -X POST http://localhost:8002/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "technical skills and experience", "top_k": 5}'
```

Optional `document_id` restricts results to one document. `top_k` is
bounded (1–50). Results are ordered by cosine similarity and include the
chunk text, document name, chunk index, page number, and score — never raw
embedding vectors. Only chunks embedded with the currently configured model
are searched; changing `EMBEDDING_MODEL_NAME`/`EMBEDDING_MODEL_VERSION`
makes existing embeddings stale and re-embeds them on the next `/embed`
call.

### Embedding configuration

See `.env.example`. Notable settings:

- `EMBEDDING_MODEL_NAME` / `EMBEDDING_MODEL_VERSION` — model identity stored
  per chunk for staleness detection.
- `EMBEDDING_BATCH_SIZE` — chunks per inference batch (default 64).
- `EMBEDDING_STALE_SECONDS` — a `processing` embedding state older than this
  is treated as interrupted and may be retried (default 3600).
- `FASTEMBED_CACHE_DIR` — model cache location (default
  `/app/storage/fastembed`).

## Question Answering & Conversations (Phase 4)

DocuLens answers natural-language questions grounded in your uploaded,
processed, and embedded documents.

### LLM providers

Two providers are supported behind a common interface:

- **Gemini** (primary) — official `google-genai` SDK, default model
  `gemini-2.5-flash`.
- **Groq** (fallback) — official `groq` SDK, default model
  `llama-3.3-70b-versatile`.

Get keys at <https://aistudio.google.com/apikey> (Gemini) and
<https://console.groq.com/keys> (Groq), then set `GEMINI_API_KEY` and/or
`GROQ_API_KEY` in `.env`. Provider order, model names, temperature, max
output tokens, and timeout are configurable (see `.env.example`).

**Fallback behavior:** the primary provider is tried first. Recoverable
failures — rate limits (429), server errors (5xx), timeouts, connection
errors, and authentication problems — fall through to the fallback
provider. Request-level errors (bad request, unknown model) and missing
credentials do not trigger a fallback. If every configured provider fails,
the API returns `502` with a safe message; answers are never fabricated to
mask provider failure. The provider and model actually used are reported
in the response metadata and stored on the assistant message.

### Asking questions

```bash
curl -X POST http://localhost:8002/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the technical skills listed?"}'
```

Optional fields: `document_id` (restrict retrieval to one document) and
`conversation_id` (continue an existing conversation — omit to start a new
one). The response contains:

- `answer` — the generated, document-grounded response.
- `conversation_id` — pass it back to ask follow-up questions.
- `citations` — source references (document ID, filename, page number when
  known, chunk index, excerpt, similarity score) for the retrieved chunks
  that support the answer. Page numbers are `null` when unavailable.
- `provider` / `model` — which LLM actually answered.
- `retrieved_chunks` — how many chunks were included in the context.

The system prompt requires the model to cite sources inline (`[1]`, `[2]`,
...) and to say clearly when the documents lack the information. Document
excerpts are treated as untrusted data — instructions embedded in uploaded
files cannot change the assistant's behavior.

### Conversation history

```bash
# list conversations
curl http://localhost:8002/api/v1/conversations

# get a conversation with all messages
curl http://localhost:8002/api/v1/conversations/{conversation_id}
```

Only the most recent `CHAT_HISTORY_LIMIT` messages are sent to the LLM;
older history is stored but not re-sent. Prior assistant answers are treated
as conversational context, not as verified document evidence.

### Retrieval & context limits

Chat retrieval reuses the Phase 3 pgvector pipeline: the question is
embedded with the same FastEmbed model, and the top `RAG_TOP_K` chunks by
cosine similarity are fetched (optionally filtered by `document_id`).
Chunks scoring below `RAG_MIN_SIMILARITY` are excluded; if nothing clears
the threshold the API returns an honest "no relevant information" answer
without calling the LLM. Context is assembled under `RAG_MAX_CONTEXT_CHARS`
with duplicate chunks removed.

## License

MIT

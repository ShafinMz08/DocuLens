# DocuLens

DocuLens is an AI-powered document intelligence platform that enables intelligent document processing, analysis, and retrieval through a web workspace.

## Features

- React + TypeScript web workspace: Document Library, AI Assistant, Semantic Search
- Document upload (PDF, DOCX, TXT), text extraction, and chunking
- Local CPU embeddings via FastEmbed (`BAAI/bge-small-en-v1.5`, 384 dimensions, pgvector)
- Automatic embedding generation as part of document processing (with a retry endpoint for failures)
- Semantic search over document chunks with cosine similarity
- Document-grounded question answering with source citations and honest abstention
- Persistent conversations with follow-up questions
- Gemini primary LLM with Groq fallback (official SDKs)
- Scalable architecture with FastAPI, PostgreSQL + pgvector, and Redis

## Architecture

```
Browser (React SPA, Vite, Tailwind)
   │  /api/* and /health via Vite dev proxy (or VITE_API_BASE_URL)
   ▼
FastAPI backend ──► PostgreSQL 16 + pgvector (documents, chunks, conversations)
   │              ──► Redis
   ├── FastEmbed (local CPU embeddings, cached in ./storage/fastembed)
   └── Gemini (primary LLM) → Groq (fallback LLM)
```

- `frontend/` — React 18 + TypeScript (strict) + Vite + Tailwind CSS +
  TanStack Query + React Router. Feature-based layout under `src/features/`,
  a typed API client in `src/lib/api.ts`, shadcn-style UI primitives in
  `src/components/ui/`.
- `backend/` — FastAPI async app; API routes under `/api/v1`, health at
  `/health`.
- `docker/` — custom PostgreSQL image with pgvector compiled from source.

## Quick Start (Docker Compose — full stack)

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local backend development without Docker)
- Node.js 20+ (for local frontend development without Docker)

### Steps

1. Copy the example environment file and fill in secrets:
   ```bash
   cp .env.example .env
   ```
   At minimum set `POSTGRES_PASSWORD`, `GEMINI_API_KEY` (or `GROQ_API_KEY`)
   for question answering. Embeddings and search work without LLM keys.

2. Start all services:
   ```bash
   docker compose up --build
   ```

3. Open the app at <http://localhost:5173> — the Vite dev server proxies
   `/api` and `/health` to the backend container.

4. Backend API is also directly reachable at `http://localhost:8002`:
   ```bash
   curl http://localhost:8002/health
   ```

The first `docker compose up` builds a custom PostgreSQL 16 Alpine image
(`docker/postgres/Dockerfile`) that compiles pgvector v0.8.1 from source —
Alpine's `postgresql-pgvector` package is not compatible with the official
Postgres image. The `vector` extension is enabled by an Alembic migration.

## Frontend

### Local development (without Docker)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies to http://localhost:8002
```

The dev server proxies `/api` and `/health` to `VITE_BACKEND_PROXY_TARGET`
(default `http://localhost:8002`; set it to `http://backend:8000` when running
inside Docker — already configured in `docker-compose.yml`).

To talk to a backend on another origin, set `VITE_API_BASE_URL` in
`frontend/.env` (see `frontend/.env.example`). The backend must then allow the
frontend origin via `CORS_ORIGINS`.

### Commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Vite dev server with API proxy |
| `npm test` | Vitest + Testing Library suite |
| `npm run typecheck` | `tsc -b` strict type check |
| `npm run build` | Type check + production build to `dist/` |

### Configuration

- `VITE_API_BASE_URL` — optional absolute backend URL (empty = same origin /
  dev proxy).
- `VITE_BACKEND_PROXY_TARGET` — proxy destination for `/api` and `/health`
  (build-time env, used by Vite config).

## Backend

The backend uses FastAPI with async PostgreSQL and Redis. Database migrations
are managed with Alembic.

To run migrations:
```bash
docker compose exec backend alembic upgrade head
```

To migrate the test database instead:
```bash
docker compose exec -e USE_TEST_DATABASE=1 backend alembic upgrade head
```

To run tests:
```bash
docker compose exec backend pytest
```

## API overview

All endpoints are versioned under `/api/v1` unless noted.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness/status |
| POST | `/api/v1/documents/upload` | Upload PDF/DOCX/TXT (multipart `file`, ≤ `MAX_UPLOAD_SIZE_BYTES`) |
| GET | `/api/v1/documents?skip&limit` | Paginated document list (`DocumentOut` includes `status`, `embedding_status`, `embedding_error`) |
| POST | `/api/v1/documents/{id}/process` | Extract → chunk → **automatically embed**; returns `document_status`, `processing_status`, `chunks_created`, `embedding_status`, `embedded_chunks`, `total_chunks`, `skipped_chunks`, `embedding_error` |
| POST | `/api/v1/documents/{id}/embed` | Re-run embedding only (retry after embedding failure or model change) |
| POST | `/api/v1/search` | Semantic search `{query, top_k (1–50), document_id?}` |
| POST | `/api/v1/chat` | Ask a question `{question, conversation_id?, document_id?}` → answer, citations, provider/model |
| GET | `/api/v1/conversations` | List conversations (paginated) |
| GET | `/api/v1/conversations/{id}` | Conversation with all messages |

Error semantics: `400` validation, `404` missing document/conversation,
`409` processing/embedding conflicts, `413` oversized upload, `422` schema
validation, `502` all LLM providers failed, `500` unexpected errors.

## Embeddings & Semantic Search

DocuLens generates embeddings locally on CPU using
[FastEmbed](https://github.com/qdrant/fastembed) with the
`BAAI/bge-small-en-v1.5` model (384 dimensions). No external API keys are
required. The model is downloaded once on first use (~100 MB) and cached in
`./storage/fastembed` (mounted into the backend container).

### Processing flow

`POST /documents/{id}/process` extracts text, chunks it, persists chunks, and
then **automatically embeds them** — there is no separate mandatory embedding
step. The response reports both the extraction outcome and the embedding
outcome (`embedding_status`, `embedded_chunks`, `total_chunks`,
`skipped_chunks`, `embedding_error`).

If embedding fails, extraction results are preserved: the document shows
`embedding_status: failed` and `POST /documents/{id}/embed` can be retried —
only missing or stale chunks are re-embedded. Repeating `/embed` is safe:
chunks already carrying the current model's embeddings are skipped.

Only chunks embedded with the currently configured model are searched;
changing `EMBEDDING_MODEL_NAME`/`EMBEDDING_MODEL_VERSION` makes existing
embeddings stale and re-embeds them on the next `/embed` call.

### Embedding configuration

See `.env.example`. Notable settings:

- `EMBEDDING_MODEL_NAME` / `EMBEDDING_MODEL_VERSION` — model identity stored
  per chunk for staleness detection.
- `EMBEDDING_BATCH_SIZE` — chunks per inference batch (default 64).
- `EMBEDDING_STALE_SECONDS` — a `processing` embedding state older than this
  is treated as interrupted and may be retried (default 3600).
- `FASTEMBED_CACHE_DIR` — model cache location (default
  `/app/storage/fastembed`).

## Question Answering & Conversations

DocuLens answers natural-language questions grounded in your uploaded,
processed, and embedded documents.

### LLM providers

Two providers are supported behind a common interface:

- **Gemini** (primary) — official `google-genai` SDK.
- **Groq** (fallback) — official `groq` SDK.

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

In the AI Assistant page you can start a new conversation, pick an existing
one, and optionally restrict retrieval to a single embedded document. The
response contains:

- `answer` — the generated, document-grounded response with inline `[n]`
  source markers that link to citation cards.
- `conversation_id` — pass it back to ask follow-up questions.
- `citations` — source references (document ID, filename, page number when
  known, chunk index, excerpt, similarity score).
- `provider` / `model` — which LLM actually answered.
- `retrieved_chunks` — how many chunks were included in the context.

The system prompt requires the model to cite sources inline and to say
clearly when the documents lack the information. Document excerpts are
treated as untrusted data — instructions embedded in uploaded files cannot
change the assistant's behavior.

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

Chat retrieval reuses the pgvector pipeline: the question is embedded with
the same FastEmbed model, and the top `RAG_TOP_K` chunks by cosine similarity
are fetched (optionally filtered by `document_id`). Chunks scoring below
`RAG_MIN_SIMILARITY` are excluded; if nothing clears the threshold the API
returns an honest "no relevant information" answer without calling the LLM.
Context is assembled under `RAG_MAX_CONTEXT_CHARS` with duplicate chunks
removed.

## Environment configuration

See `.env.example` for the full list. Key groups:

- **Database/Redis**: `POSTGRES_*`, `DATABASE_URL`, `SYNC_DATABASE_URL`,
  `TEST_DATABASE_URL`, `REDIS_URL`
- **App**: `APP_NAME`, `APP_VERSION`, `DEBUG`, `LOG_LEVEL`
- **Server/CORS**: `HOST`, `PORT`, `CORS_ORIGINS` (comma-separated frontend
  origins allowed by the backend — default `http://localhost:5173,http://localhost:3000`)
- **Uploads**: `DOCUMENT_STORAGE_DIR`, `MAX_UPLOAD_SIZE_BYTES` (default 20 MB)
- **Embeddings**: `EMBEDDING_*`, `FASTEMBED_CACHE_DIR`
- **LLM**: `GEMINI_*`, `GROQ_*`, `LLM_*`
- **RAG/chat**: `RAG_*`, `CHAT_*`
- **Frontend (Vite)**: `VITE_API_BASE_URL`, `VITE_BACKEND_PROXY_TARGET`
  (see `frontend/.env.example`)

## Testing

Frontend:
```bash
cd frontend
npm test            # Vitest + React Testing Library (mocked API layer)
npm run typecheck
npm run build
```

Backend:
```bash
docker compose exec backend pytest
```

## Current limitations

- No authentication or per-user data isolation — anyone who can reach the backend can access the shared application data. Do not expose a deployment to untrusted networks until authentication, authorization, and abuse protection are implemented.
- No document deletion or preview endpoints.
- Chat answers are returned complete (no token streaming).
- Processing/embedding status is refreshed after actions or manually; there is no automatic status polling or server-sent progress reporting.
- Conversation titles are auto-derived; there is no rename/delete UI.
- The semantic-search `document_id` filter and chat context selector only
  list fully embedded documents.

## Production deployment prerequisites

Before public deployment:

1. **Authentication & authorization** — the API currently has none; add a
   proper authn/authz layer plus abuse protection (rate limiting).
2. **Restrictive CORS** — set `CORS_ORIGINS` to the exact frontend origin(s);
   never use `*` with credentials.
3. **Frontend build** — `npm run build` produces `frontend/dist`; serve it
   via a static host/CDN and point `VITE_API_BASE_URL` at the backend (or
   serve same-origin).
4. **Secrets management** — inject `GEMINI_API_KEY`/`GROQ_API_KEY` and DB
   credentials via a secrets manager, never in committed files.
5. **Persistence** — keep the `postgres_data` volume and document/fastembed
   storage mounts backed up.
6. **TLS & hardening** — terminate TLS at a reverse proxy; set `DEBUG=false`.

## License

MIT

# DocuLens

DocuLens is an AI-powered document intelligence platform that enables intelligent document processing, analysis, and retrieval.

## Features

- Document upload, text extraction, and chunking
- Local CPU embeddings via FastEmbed (`BAAI/bge-small-en-v1.5`, 384 dimensions, pgvector)
- Semantic search over document chunks with cosine similarity
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

## License

MIT

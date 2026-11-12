# DocuLens

DocuLens is an AI-powered document intelligence platform that enables intelligent document processing, analysis, and retrieval.

## Features

- AI-powered document analysis
- Intelligent document search and retrieval
- Scalable architecture with FastAPI, PostgreSQL, and Redis

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

To run tests:
```bash
docker-compose exec backend pytest
```

## License

MIT

# Asset Compliance AI

Serverless, multi-agent AI microservice for automated physical asset compliance auditing. Built with FastAPI, LangGraph, Anthropic Claude, and AWS Lambda with response streaming.

## Overview

Asset Compliance AI is a standalone microservice that integrates with an existing Django-based physical asset management system. When an auditor uploads photos and remarks through the Django frontend, Django calls this service's REST API to:

1. **Ingest** asset documentation (PDFs, images) into a Pinecone vector database
2. **Run** a multi-agent compliance audit against uploaded photos and auditor remarks
3. **Query** an auditor Q&A chat backed by three-tier RAG fallback

## Architecture

```
Django Frontend
     │ X-API-Key
     ▼
Lambda Function URL (IAM + NDJSON streaming)
     │
FastAPI (Mangum ASGI adapter)
     │
LangGraph Pipeline
     ├── Document Agent  ── Pinecone RAG retrieval
     ├── Image Agent     ── Claude Vision analysis
     ├── Rule Agent      ── LLM compliance cross-reference
     ├── Evidence Agent  ── Data consolidation (no LLM)
     └── Verdict Agent   ── Structured verdict generation
```

## Authentication

All API requests (except `GET /health`) must include the shared API key:

```
X-API-Key: <your-API_SECRET_KEY>
```

The key is validated using `hmac.compare_digest` (timing-safe). It must match the `API_SECRET_KEY` in `.env` / SSM Parameter Store, which is the same key configured on the Django side.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (unauthenticated) |
| `POST` | `/api/v1/ingest` | Ingest asset documents into Pinecone |
| `POST` | `/api/v1/audit/run` | Run multi-agent audit (NDJSON streaming) |
| `POST` | `/api/v1/chat/query` | Auditor Q&A with RAG fallback |

## Project Structure

```
multi_agent_asset_compliance_system/
├── app/
│   ├── main.py              # FastAPI app factory + Mangum Lambda handler
│   ├── config.py            # Pydantic Settings (all secrets via SecretStr)
│   ├── dependencies.py      # FastAPI DI providers for external clients
│   ├── api/
│   │   └── v1/
│   │       ├── router.py    # v1 API router
│   │       ├── ingest.py    # Document ingestion endpoint
│   │       ├── audit.py     # Streaming audit endpoint
│   │       └── chat.py      # Chat Q&A endpoint
│   ├── agents/
│   │   ├── state.py         # LangGraph AuditState TypedDict
│   │   ├── graph.py         # LangGraph pipeline assembly
│   │   ├── document_agent.py
│   │   ├── image_agent.py
│   │   ├── rule_agent.py
│   │   ├── evidence_agent.py
│   │   └── verdict_agent.py
│   ├── schemas/
│   │   ├── ingest.py
│   │   ├── audit.py
│   │   └── chat.py
│   ├── services/
│   │   ├── pinecone_service.py
│   │   ├── embedding_service.py
│   │   ├── s3_service.py
│   │   ├── document_loader.py
│   │   └── web_search_service.py
│   └── utils/
│       ├── logger.py
│       ├── exceptions.py
│       └── streaming.py
├── tests/
│   ├── conftest.py          # Shared fixtures (moto S3, mock clients)
│   ├── unit/
│   └── integration/
├── infra/
│   └── ssm_bootstrap.sh     # Seed SSM Parameter Store from .env
├── scripts/
│   └── local_invoke.py      # Local dev helper
├── template.yaml            # AWS SAM template
├── samconfig.toml
├── requirements.txt
├── requirements-dev.txt
├── Makefile
└── .env.example
```

## Quick Start

### Prerequisites

- Python 3.12+
- AWS CLI configured
- AWS SAM CLI (for deployment)

### Local Development

```bash
# 1. Copy and fill in your secrets
cp .env.example .env

# 2. Install dependencies
make install-dev

# 3. Run locally with hot reload
make local-api
# → API docs: http://localhost:8000/docs
# → Health:   http://localhost:8000/health
```

### Running Tests

```bash
# All tests
make test

# Unit tests only
make test-unit

# Integration tests only
make test-integration

# With coverage report
make test-cov
```

### Code Quality

```bash
make lint       # Ruff lint
make format     # Ruff format (in-place)
make typecheck  # Mypy type checking
```

## Deployment

### 1. Bootstrap SSM Parameters

Seed all API keys and config values into AWS SSM Parameter Store:

```bash
ENV=production make ssm-bootstrap
```

> This reads from your local `.env` file. Run once per environment.

### 2. Build and Deploy

```bash
# Build the Lambda deployment package
make sam-build

# Deploy to production
make deploy-prod

# Deploy to staging
make deploy-staging
```

### 3. Configure Django

After deployment, SAM outputs the Lambda Function URL. Set it in Django's settings:

```python
COMPLIANCE_SERVICE_URL = "https://<function-url>.lambda-url.us-east-1.on.aws"
COMPLIANCE_SERVICE_API_KEY = "<same value as API_SECRET_KEY in .env>"
```

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

| Variable | Description | Required |
|----------|-------------|----------|
| `AWS_REGION` | AWS region | ✓ |
| `S3_BUCKET_NAME` | S3 bucket for documents | ✓ |
| `PINECONE_API_KEY` | Pinecone API key | ✓ |
| `PINECONE_INDEX_NAME` | Pinecone index name | ✓ |
| `PINECONE_ENVIRONMENT` | Pinecone environment | ✓ |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) API key | ✓ |
| `ANTHROPIC_MODEL` | Claude model ID | ✓ |
| `OPENAI_API_KEY` | OpenAI API key (embeddings) | ✓ |
| `EMBEDDING_MODEL` | OpenAI embedding model | ✓ |

| `API_SECRET_KEY` | Shared secret with Django | ✓ |
| `LANGCHAIN_API_KEY` | LangSmith API key (optional) | — |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | — |

## Audit Stream Format (NDJSON)

The `POST /api/v1/audit/run` endpoint streams results as newline-delimited JSON:

```jsonl
{"event": "node_complete", "node": "document_agent", "progress": 0.2, "asset_id": "...", "run_id": "..."}
{"event": "node_complete", "node": "image_agent", "progress": 0.4, "asset_id": "...", "run_id": "..."}
{"event": "node_complete", "node": "rule_agent", "progress": 0.6, "asset_id": "...", "run_id": "..."}
{"event": "node_complete", "node": "evidence_agent", "progress": 0.8, "asset_id": "...", "run_id": "..."}
{"event": "node_complete", "node": "verdict_agent", "progress": 1.0, "asset_id": "...", "run_id": "..."}
{"event": "verdict", "verdict": {"compliance_status": "NON_COMPLIANT", "confidence": 0.87, ...}}
```

## Security Notes

- **API key auth**: timing-safe comparison via `hmac.compare_digest`
- **No secrets in code**: all keys via `SecretStr` from `.env` / SSM
- **S3 bucket**: private, versioned, encrypted at rest (AES-256)
- **Lambda Function URL**: IAM-authenticated (no unauthenticated access)
- **Docs endpoint**: disabled in production (`APP_ENV=production`)
- **Logging**: structured JSON — secrets are never logged

## License

MIT
# Asset Compliance AI

Serverless, multi-agent AI microservice for automated physical asset compliance auditing. Built with FastAPI, LangGraph, Anthropic Claude, and AWS Lambda with response streaming.

## Overview

Asset Compliance AI is a standalone microservice that integrates with an existing backend-driven physical asset management system. When an auditor uploads photos and remarks through the backend client, backend client calls this service's REST API to:

1. **Ingest** asset documentation (PDFs, images) into a Pinecone vector database
2. **Run** a multi-agent compliance audit against uploaded photos and auditor remarks
3. **Query** an auditor Q&A chat backed by three-tier RAG fallback

## Documentation

For deep dives into how the system operates and how to run it, please refer to the dedicated documentation files:
- [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — A step-by-step narrative of the entire project lifecycle.
- [docs/PROJECT_FLOW.md](docs/PROJECT_FLOW.md) — Detailed technical architecture and agent flow.
- [docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md) — Guide for local setup, Python running, and Docker deployment.

## How it Works (Core Flow)

1. **Ingestion:** backend client uploads compliance manuals (PDFs) to S3 and calls `/api/v1/ingest`. The AI parses the text, creates vector embeddings (via OpenAI/Anthropic), and stores them in Pinecone under an isolated `asset_id` namespace.
2. **On-Site Audit:** An auditor uploads photos and remarks via the backend client, triggering the `/api/v1/audit/run` endpoint.
3. **LangGraph Pipeline:**
   - **Document Agent:** Semantically searches Pinecone for the exact rules applying to the asset.
   - **Image Agent:** Uses a Vision LLM to analyse the auditor's photos for defects and labels.
   - **Rule Agent:** Cross-references the image findings against the retrieved document rules.
   - **Evidence Agent:** Compiles a traceable "Evidence Bundle" mapping rules to photos/remarks.
   - **Verdict Agent:** Acts as the Senior Auditor, issuing a final JSON compliance verdict (e.g., `COMPLIANT`, `NON_COMPLIANT`).
4. **Auditor Chat:** Auditors can query the asset using the `/api/v1/chat/query` endpoint, which uses a highly resilient **3-Tier RAG Fallback** (Pinecone → Asset Spec → Web Search via DuckDuckGo).
5. **GDPR Erasure:** If an asset is deleted, the `/api/v1/admin/assets/{asset_id}` endpoint safely purges all S3 images, Pinecone vectors, and DynamoDB logs.

## Architecture

```
backend client
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

The key is validated using `hmac.compare_digest` (timing-safe). It must match the `API_SECRET_KEY` in `.env` / SSM Parameter Store, which is the same key configured on the backend client side.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (unauthenticated) |
| `POST` | `/api/v1/ingest` | Ingest asset documents into Pinecone |
| `POST` | `/api/v1/audit/run` | Run multi-agent audit (NDJSON streaming) |
| `POST` | `/api/v1/chat/query` | Auditor Q&A with RAG fallback (Pinecone, Asset Spec, Web Search) |
| `DELETE` | `/api/v1/admin/assets/{asset_id}` | GDPR Right-to-Erasure (Purges S3, Pinecone, DynamoDB) |

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

### 3. Configure backend client

After deployment, SAM outputs the Lambda Function URL. Set it in backend client's settings:

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
| `API_SECRET_KEY` | Shared secret with backend client | ✓ |
| `CORS_ALLOWED_ORIGINS` | JSON array of allowed origins (No `*` in prod) | ✓ |

### LLM Providers & Agent Configuration
You only need to supply keys for the providers you actually use. You can mix and match models for each agent.

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key (e.g. for embeddings) | Optional |
| `ANTHROPIC_API_KEY` | Anthropic API key | Optional |
| `GOOGLE_API_KEY` | Google Gemini API key | Optional |
| `XAI_API_KEY` | xAI Grok API key | Optional |
| `IMAGE_AGENT_PROVIDER` / `_MODEL` | Provider and model for Image analysis | ✓ |
| `RULE_AGENT_PROVIDER` / `_MODEL` | Provider and model for Rule evaluation | ✓ |
| `VERDICT_AGENT_PROVIDER` / `_MODEL` | Provider and model for final verdict | ✓ |
| `CHAT_AGENT_PROVIDER` / `_MODEL` | Provider and model for Auditor chat | ✓ |
| `EMBEDDING_PROVIDER` / `_MODEL` | Provider and model for Pinecone embeddings | ✓ |

### Tuning & Limits
| Variable | Description | Default |
|----------|-------------|----------|
| `LLM_MAX_TOKENS` | Max tokens for verdict generation | 4096 |
| `LLM_CHAT_MAX_TOKENS` | Max tokens for chat responses | 1024 |
| `EVIDENCE_BUNDLE_CAP` | Max evidence items to prevent context overflow | 20 |
| `AUDIT_TIMEOUT_SECONDS` | Timeout for the full audit pipeline | 120 |
| `RATE_LIMIT_AUDIT` | Throttling for audit requests | 10/minute |
| `RATE_LIMIT_INGEST` | Throttling for document ingestion | 30/minute |
| `RATE_LIMIT_CHAT` | Throttling for auditor Q&A | 60/minute |
| `LANGCHAIN_API_KEY` | LangSmith API key for tracing | Optional |

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

Apache License 2.0
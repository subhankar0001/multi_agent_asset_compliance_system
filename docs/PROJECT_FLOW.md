# Asset Compliance AI: Detailed Project Flow

This document outlines the end-to-end data flow, architecture, and agent interactions of the Asset Compliance AI system. It is intended for developers and architects to understand exactly how the system processes data from ingestion to the final compliance verdict.

---

## 1. High-Level Architecture

The system is a FastAPI-based serverless microservice designed to act as the AI compliance backend for an upstream orchestrator (like a backend client Enterprise Management System). 

It has four primary operational domains:
1. **Ingestion (`/api/v1/ingest`)**: Vectorises and stores compliance standard documents (PDFs) into Pinecone.
2. **Audit Pipeline (`/api/v1/audit/run`)**: A Multi-Agent LangGraph pipeline that reviews images, remarks, and documents to issue a compliance verdict.
3. **Auditor Chat (`/api/v1/chat/query`)**: A conversational interface for auditors to query asset documents with a 3-tier RAG fallback.
4. **Administration (`/api/v1/admin/*`)**: Handles GDPR "Right to Erasure" requirements by purging all tenant data.

The system relies on **AWS S3** for blob storage, **Pinecone** for vector search, **DynamoDB** for idempotency/audit history, and **LLM APIs** (OpenAI, Anthropic, xAI, etc.) for agent cognition.

---

## 2. Document Ingestion Flow (`POST /api/v1/ingest`)

Before an asset can be audited, the compliance standards (User Manuals, Safety Sheets, Regulations) must be ingested.

1. **Trigger:** The backend client uploads PDF documents to S3 and calls the ingestion endpoint.
2. **Download & Parse:** The system downloads the raw bytes from S3 and uses PyMuPDF (via `document_loader.py`) to extract text.
3. **Chunking:** The text is chunked into overlapping segments (default 512 characters, 64 overlap).
4. **Embedding:** The chunks are sent in batches to the configured Embedding Provider (e.g., `text-embedding-3-small`).
5. **Storage:** The resulting vectors are upserted into **Pinecone**.
   - **Crucial Isolation:** All vectors for a given asset are stored inside a specific Pinecone namespace (`asset_{asset_id}`). This guarantees strict multi-tenant data isolation.

---

## 3. The Multi-Agent Audit Pipeline (`POST /api/v1/audit/run`)

When an auditor performs a field inspection, they upload photos and remarks. The backend client calls the audit endpoint to evaluate if the asset is compliant.

The audit runs as a **LangGraph State Machine** consisting of 5 sequential agents. It streams progress events via NDJSON so the client can display real-time updates.

### Agent 1: Document Agent (`document_agent.py`)
- **Input:** `asset_spec` (metadata like name, model, manufacturer).
- **Task:** Generates a semantic search query based on the asset spec and queries Pinecone.
- **Output:** Retrieves the top-K relevant compliance chunks (e.g., maintenance requirements, safety limits) to be used as ground truth.

### Agent 2: Image Agent (`image_agent.py`)
- **Input:** `s3_image_keys` (field photos uploaded by the auditor).
- **Task:** Downloads the images from S3, encodes them as base64, and sends them to a multimodal Vision LLM (e.g., GPT-4o).
- **Output:** Extracts structured findings from the images: visible defects, conditions (good, poor, critical), and legible warning labels. *(Note: Image processing is parallelised via `asyncio.gather` for speed).*

### Agent 3: Rule Agent (`rule_agent.py`)
- **Input:** Ground truth docs (from Agent 1) + Image findings (from Agent 2) + `auditor_remarks`.
- **Task:** Cross-references the real-world findings against the retrieved compliance rules.
- **Output:** Emits a JSON array of specific `TriggeredRules` (e.g., "Rule 4.2 Violated: Rust observed on primary valve. Severity: Major").

### Agent 4: Evidence Agent (`evidence_agent.py`)
- **Input:** Triggered rules and raw findings.
- **Task:** Compiles a clean, normalised "Evidence Bundle". It maps exactly which piece of evidence (image, remark, or document) supports which triggered rule, ensuring the final verdict is 100% traceable.

### Agent 5: Verdict Agent (`verdict_agent.py`)
- **Input:** The Evidence Bundle + Previous historical verdicts.
- **Task:** Acts as the Senior Compliance Officer. Synthesises all data to make a final ruling.
- **Output:** A highly structured `AuditVerdict` containing:
  - `compliance_status`: `COMPLIANT`, `NON_COMPLIANT`, `NEEDS_REVIEW`, or `INSUFFICIENT_DATA`
  - `confidence`: (0.0 to 1.0)
  - `recommendations`: Actionable next steps.
  - `verdict_reasoning`: A natural language explanation.

---

## 4. Chat Q&A Fallback Strategy (`POST /api/v1/chat/query`)

Auditors can ask questions about the asset (e.g., "What is the maximum operating pressure?"). The chat endpoint implements a highly resilient **3-Tier Fallback** strategy:

1. **Tier 1 (Pinecone RAG):** Embeds the question and searches the asset's Pinecone namespace. If the highest similarity score is >= `0.75`, it uses the retrieved documents to answer the question, citing the specific PDF and page number.
2. **Tier 2 (Asset Spec Fallback):** If Pinecone yields no relevant results (score < `0.75`), it falls back to answering using the `asset_spec` metadata and previous historical audit verdicts.
3. **Tier 3 (Web Search Augmentation):** If relying on Tier 2, the system also executes a web search (via DuckDuckGo/Tavily) using the asset name and question. It injects the web results into the prompt context, explicitly instructing the LLM to inform the user that the answer was sourced from the web, not internal documents.

---

## 5. Administration & Data Lifecycle

### Security & Fault Tolerance
- **API Key Auth:** All endpoints (except `/health`) require an `X-API-Key` matching the server's secret.
- **Prompt Injection Defense:** `auditor_remarks` are automatically HTML-escaped, and `asset_spec` is strictly enforced as a Pydantic model to prevent malicious overrides.
- **Circuit Breakers:** All external calls to Pinecone and LLM providers are wrapped in a custom `CircuitBreaker`. If a vendor experiences an outage (3 consecutive failures), the circuit trips open for 60 seconds, returning graceful fallbacks (like `INSUFFICIENT_DATA`) rather than bottlenecking the server with retry storms.

### GDPR Erasure (`DELETE /api/v1/admin/assets/{asset_id}`)
To comply with data privacy and data retention laws, the system provides a hard-delete endpoint that:
1. Scans and deletes all vectors in the specific Pinecone namespace.
2. Lists and purges all documents and images associated with the `asset_id` prefix in S3.
3. Marks related audit runs in DynamoDB as `ERASED`.

# How to Run the Asset Compliance AI System

This guide outlines how to run the multi-agent system locally for development, testing, and production deployment on a single EC2 instance.

## 1. Prerequisites

Before you begin, ensure you have the following installed and configured:
- **Python 3.12+**
- **Docker** (for containerised runs)
- **AWS CLI** (Configured with an IAM user that has access to S3, DynamoDB, and Bedrock/SSM if used)
- A **Pinecone Account** & API Key
- An **LLM API Key** (e.g., OpenAI, Anthropic, or Google)

---

## 2. Environment Configuration

1. Clone the repository.
2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and fill in the required variables:
   - `API_KEY`: A secure string used to authenticate the backend client (e.g., `super_secret_key`).
   - `S3_BUCKET_NAME`: The AWS S3 bucket where you will store asset documents and images.
   - `DYNAMODB_TABLE_NAME`: The AWS DynamoDB table for audit runs.
   - `PINECONE_API_KEY`: Your Pinecone API key.
   - `PINECONE_HOST`: Your Pinecone index host URL.
   - **LLM API Keys**: Provide at least one valid key (e.g., `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) based on your configured `model_provider` in `app/config.py`.

*Note: If running in AWS natively, the application will automatically attempt to bootstrap missing environment variables from AWS Systems Manager (SSM) Parameter Store using the `/compliance-ai/dev/` prefix.*

---

## 3. Local Development (Native Python)

We recommend using a virtual environment.

1. **Create and activate a virtual environment:**
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Run the server via Uvicorn:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

The API will now be accessible at `http://localhost:8000`. 
You can view the interactive Swagger documentation at `http://localhost:8000/docs`.

### Running Tests
To run the automated test suite, ensure your `.env` has placeholder variables (or valid testing variables), then run:
```bash
pytest tests/ -v
```

---

## 4. Running via Docker

For a production-like environment (e.g., deploying to a single EC2 instance), you can run the system using Docker.

1. **Build the Docker Image:**
   ```bash
   docker build -t asset-compliance-ai .
   ```

2. **Run the Container:**
   Pass your AWS credentials and the `.env` file into the container:
   ```bash
   docker run -d \
     --name compliance-ai \
     -p 8000:8000 \
     --env-file .env \
     -e AWS_ACCESS_KEY_ID=your_access_key \
     -e AWS_SECRET_ACCESS_KEY=your_secret_key \
     -e AWS_DEFAULT_REGION=eu-west-1 \
     asset-compliance-ai
   ```

*(Note: If you are running this Docker container on an EC2 instance that has an assigned IAM Instance Profile, you do not need to explicitly pass the AWS access keys; the container's AWS SDK will automatically inherit the instance role).*

---

## 5. Basic API Usage

All API calls must include the `X-API-Key` header matching the `API_KEY` set in your environment.

### A. Check Health
```bash
curl -X GET http://localhost:8000/health
```

### B. Ingest a Document
Uploads and vectorises a compliance document into Pinecone:
```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "X-API-Key: your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "ASSET-123",
    "s3_key": "ASSET-123/manual.pdf",
    "doc_type": "user_manual"
  }'
```

### C. Run an Audit
Triggers the multi-agent LangGraph pipeline (streams results via NDJSON):
```bash
curl -X POST http://localhost:8000/api/v1/audit/run \
  -H "X-API-Key: your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "ASSET-123",
    "run_id": "RUN-001",
    "asset_spec": {"name": "Industrial Valve", "model": "V-900"},
    "s3_image_keys": ["ASSET-123/inspections/photo1.jpg"],
    "auditor_remarks": "There is noticeable rust on the primary gauge."
  }'
```

### D. Auditor Chat
Chat with the asset's specific documents:
```bash
curl -X POST http://localhost:8000/api/v1/chat/query \
  -H "X-API-Key: your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "ASSET-123",
    "asset_spec": {"name": "Industrial Valve", "model": "V-900"},
    "question": "What is the acceptable rust tolerance for the primary gauge?"
  }'
```

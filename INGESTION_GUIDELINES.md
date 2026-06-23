# Enterprise Document Ingestion & Embedding Guidelines

This guide details how to prepare, structure, and execute asset documentation ingestion for the **Asset Compliance AI** microservice. Following these guidelines ensures high retrieval accuracy (RAG) during compliance auditing.

---

## 1. Supported Document Types & Formats

The ingestion pipeline handles files stored in your enterprise Amazon S3 bucket.

### Document Classifications (`doc_type`)
When registering a file, you must assign one of the following classification tags:
* `user_manual`: Equipment operating manuals, technical reference booklets, and manufacturer instructions.
* `safety_sheet`: Material Safety Data Sheets (MSDS), hazard notices, and safety guidelines.
* `compliance_spec`: Site rules, government regulations, or corporate compliance standards.
* `installation_image`: On-site photographs showing the physical installation of the asset.
* `other`: Any auxiliary document that doesn't fit the above but contains context for auditing.

### File Format Requirements
| File Type | Supported Formats | Processing Method | Preparation Guidelines |
| :--- | :--- | :--- | :--- |
| **Documents** | PDF (`.pdf`) | Text extracted page-by-page (using `pypdf`) and split into overlapping character-level chunks. | **Must contain text layers.** If you have scanned physical paper, run **OCR (Optical Character Recognition)** before uploading. Passwords or encryption must be removed. |
| **Images** | JPEG (`.jpg`, `.jpeg`), PNG (`.png`), WebP (`.webp`) | Transmitted as Base64 to **Claude LLM Vision** to produce a dense text description, which is then embedded as a single vector. | Use high-resolution images. Ensure labels, barcodes, rating plates, or warning stickers are legible, well-lit, and un-obscured. |

---

## 2. Ingestion Lifecycles & Batching

The `POST /api/v1/ingest` API supports multiple document ingestion patterns depending on the state of the asset in your database:

1. **`create` (Initial Asset Registration):**
   * Use this when registering an asset for the first time.
   * **Idempotency Guard:** If the asset's Pinecone namespace already has vectors, the system will skip reprocessing to prevent redundant cost and API usage.
   * **Batching:** You can send a list of up to 50 documents in a single request.
2. **`add` (Append Documentation):**
   * Use this to add new manuals, specifications, or images to an asset that has already been registered.
   * New document chunks are embedded and appended to the existing namespace.
3. **`update` (Surgical Replacement):**
   * Use this to update a specific document (e.g., uploading a newer version of a manual).
   * **Exactly one document** must be sent in the request list.
   * The pipeline automatically locates and deletes all old vector chunks matching the `doc_id` inside the namespace, then embeds and writes the new file.

4. **GDPR Erasure (Right-to-Erasure):**
   * To completely wipe an asset's records from the system, do not use the ingest endpoint.
   * Instead, call `DELETE /api/v1/admin/assets/{asset_id}`. This purges Pinecone vectors, S3 documents, S3 images, and DynamoDB logs.

---

## 3. Preparing Files for Ingestion (Enterprise Best Practices)

To maximize RAG retrieval efficiency and compliance audit accuracy:
* **Strict S3 Key Formatting:** To prevent directory traversal attacks, `s3_key` values must strictly adhere to the regex `^[a-zA-Z0-9/_\-\.]+$`. Do not use spaces or special characters in filenames or paths.
* **Stable Document IDs (`doc_id`):** Your main database (e.g., backend client) must assign and maintain stable, unique identifiers for documents. When replacing a manual, keep the same `doc_id` and send it with the `update` lifecycle event.
* **Keep Documents Segmented:** Rather than merging all manuals into one giant PDF, upload them as separate S3 keys and register them as individual items. This ensures accurate source-attribution and file citations.
* **Avoid Non-Standard File Types:** Word documents (`.docx`), Excel files (`.xlsx`), or plain text (`.txt`) are not natively chunked. Convert text guidelines into PDFs before uploading to S3.

---

## 4. How to Execute Ingestions (API Integration)

All requests must include the timing-safe shared API key in the headers.

### Endpoint Details
* **Method:** `POST`
* **Path:** `/api/v1/ingest`
* **Header:** `X-API-Key: <your-API_SECRET_KEY>`
* **Content-Type:** `application/json`

### Example Request Body (Batch Ingest on Create)
```json
{
  "asset_id": "8a3d5e21-9654-4f2e-bf72-87adac23b102",
  "event": "create",
  "documents": [
    {
      "s3_key": "raw-uploads/pump_5000_user_guide.pdf",
      "doc_id": "doc-manual-5000",
      "doc_type": "user_manual",
      "filename": "pump_5000_user_guide.pdf"
    },
    {
      "s3_key": "raw-uploads/pump_5000_safety.pdf",
      "doc_id": "doc-safety-5000",
      "doc_type": "safety_sheet",
      "filename": "pump_5000_safety.pdf"
    },
    {
      "s3_key": "raw-uploads/pump_5000_installation_photo.png",
      "doc_id": "doc-photo-5000",
      "doc_type": "installation_image",
      "filename": "pump_5000_installation_photo.png"
    }
  ]
}
```

### Python Integration Example (Backend/Enterprise Client)
```python
import requests
import json

COMPLIANCE_SERVICE_URL = "https://<your-lambda-url>.lambda-url.us-east-1.on.aws"
API_KEY = "your-shared-api-secret-key"

payload = {
    "asset_id": "8a3d5e21-9654-4f2e-bf72-87adac23b102",
    "event": "create",
    "documents": [
        {
            "s3_key": "assets/manuals/HP-5000.pdf",
            "doc_id": "manual-hp-5000-v1",
            "doc_type": "user_manual",
            "filename": "HP-5000_User_Manual.pdf"
        }
    ]
}

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

response = requests.post(
    f"{COMPLIANCE_SERVICE_URL}/api/v1/ingest",
    headers=headers,
    data=json.dumps(payload)
)

if response.status_code == 200:
    data = response.json()
    print(f"Success! Namespace: {data['namespace']}, Vectors Upserted: {data['vectors_upserted']}")
else:
    print(f"Failed: {response.status_code} - {response.text}")
```

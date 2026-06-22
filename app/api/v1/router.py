"""
API v1 router — mounts all endpoint routers under /api/v1.

Each sub-router handles a distinct workflow:
  /ingest  — document ingestion pipeline
  /audit   — multi-agent compliance audit
  /chat    — auditor Q&A with RAG fallback
  /admin   — operational stats and GDPR data erasure
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.audit import router as audit_router
from app.api.v1.chat import router as chat_router
from app.api.v1.ingest import router as ingest_router

api_router = APIRouter()
api_router.include_router(ingest_router)
api_router.include_router(audit_router)
api_router.include_router(chat_router)
api_router.include_router(admin_router)

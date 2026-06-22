"""
Image agent — analyse each audit photo using LLM vision.

For each S3 key in state["s3_image_keys"], this node:
  1. Downloads the image as base64 from S3
  2. Passes it to the configured Claude model with a structured analysis prompt
  3. Parses the JSON response into an ImageAnalysis TypedDict

The prompt enforces a strict JSON response format so downstream agents
can rely on the structure without further LLM calls.

Non-fatal errors per image are caught and accumulated in state["errors"]
so that one bad image does not abort the entire audit.

Populates: state["image_analyses"]
"""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.state import AuditState, ImageAnalysis
from app.config import get_settings
from app.dependencies import get_image_agent_llm, get_s3_client
from app.services import s3_service

logger = structlog.get_logger(__name__)

_IMAGE_ANALYSIS_PROMPT = """Analyse this audit photograph of a physical asset for compliance purposes.

Be precise and technical. Document every visible defect, label, and condition indicator."""


class ImageAnalysisOutput(BaseModel):
    findings: list[str]
    labels: list[str]
    condition: str
    raw_description: str


async def image_agent_node(state: AuditState) -> dict[str, Any]:
    """
    Analyse each audit image using Claude vision.

    Downloads images from S3 as base64 and sends them to the configured LLM with a
    structured analysis prompt. Parses the JSON response into ImageAnalysis
    TypedDicts. Per-image errors are caught and accumulated.

    Returns:
        dict with keys: image_analyses, errors
    """
    settings = get_settings()
    llm = get_image_agent_llm()
    s3_client = get_s3_client()

    analyses: list[ImageAnalysis] = []
    errors: list[str] = list(state.get("errors", []))

    for s3_key in state.get("s3_image_keys", []):
        try:
            image_b64 = s3_service.download_as_base64(s3_client, settings.s3_bucket_name, s3_key)
            filename = s3_key.rsplit("/", 1)[-1]
            media_type = s3_service.infer_media_type(filename)

            # LangChain standard multimodal format
            image_url = f"data:{media_type};base64,{image_b64}"

            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": _IMAGE_ANALYSIS_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                )
            ]

            structured_llm = llm.with_structured_output(ImageAnalysisOutput)
            parsed_obj: ImageAnalysisOutput = await structured_llm.ainvoke(messages)  # type: ignore[assignment]

            analysis: ImageAnalysis = {
                "s3_key": s3_key,
                "findings": parsed_obj.findings,
                "labels": parsed_obj.labels,
                "condition": parsed_obj.condition,
                "raw_description": parsed_obj.raw_description,
            }
            analyses.append(analysis)
            logger.debug(
                "image_analysed",
                s3_key=s3_key,
                condition=analysis["condition"],
                findings_count=len(analysis["findings"]),
            )

        except Exception as exc:
            logger.error("image_agent_error", s3_key=s3_key, error=str(exc))
            errors.append(f"image_agent: {s3_key}: {exc}")

    logger.info(
        "image_agent_complete",
        images_analysed=len(analyses),
        errors_count=len(errors),
    )
    return {"image_analyses": analyses, "errors": errors}

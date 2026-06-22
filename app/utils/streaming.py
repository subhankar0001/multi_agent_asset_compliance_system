"""
NDJSON streaming helpers for Lambda Response Streaming.

Used by the audit router to emit progress events and the final verdict
as newline-delimited JSON (NDJSON), one line per event.

Each event is a typed dataclass that serialises to a JSON dict.
The Django client reads the stream line-by-line and parses each line
independently — if one line fails, others are unaffected.

Event types:
  - NodeCompleteEvent: emitted after each LangGraph node finishes
  - VerdictEvent: emitted once when the verdict agent completes
  - ErrorEvent: emitted if a recoverable error occurs mid-stream
"""

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class NodeCompleteEvent:
    """Emitted after each LangGraph agent node completes."""

    event: str = "node_complete"
    node: str = ""
    asset_id: str = ""
    run_id: str = ""
    progress: float = 0.0  # 0.0 - 1.0


@dataclass
class VerdictEvent:
    """Emitted when the verdict agent produces the final compliance verdict."""

    event: str = "verdict"
    verdict: dict[str, Any] | None = None


@dataclass
class ErrorEvent:
    """Emitted when a non-fatal error occurs during the audit pipeline."""

    event: str = "error"
    message: str = ""
    node: str = ""


def serialise_event(event: NodeCompleteEvent | VerdictEvent | ErrorEvent) -> str:
    """
    Serialise an event dataclass to a JSON string with a trailing newline.

    The trailing newline is required for NDJSON format and allows the
    receiving client to split the stream on newlines.
    """
    return json.dumps(asdict(event), default=str) + "\n"

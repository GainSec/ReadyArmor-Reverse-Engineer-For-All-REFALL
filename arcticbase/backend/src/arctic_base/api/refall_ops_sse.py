from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse

from arctic_base.api.refall_ops import require_ops
from arctic_base.config import Settings

router = APIRouter(prefix="/refall/ops", tags=["refall-ops-events"])

_EVENTS: deque[dict[str, Any]] = deque(maxlen=200)


def record_event(event: dict[str, Any]) -> dict[str, Any]:
    item = dict(event)
    item.setdefault("ts", datetime.now(UTC).isoformat())
    _EVENTS.append(item)
    return item


@router.post("/events/push", operation_id="pushRefallOpsEvent")
def push_event(
    event: Annotated[dict[str, Any], Body()],
    settings: Annotated[Settings, Depends(require_ops)],
) -> dict:
    del settings
    item = record_event(event)
    return {"ok": True, "event": item}


@router.get("/feed/history", operation_id="getRefallOpsFeedHistory")
def feed_history(settings: Annotated[Settings, Depends(require_ops)]) -> dict:
    del settings
    return {"events": list(_EVENTS)}


@router.get("/feed", operation_id="getRefallOpsFeed")
async def feed(settings: Annotated[Settings, Depends(require_ops)]) -> StreamingResponse:
    del settings

    async def gen():
        for event in list(_EVENTS):
            yield f"data: {json.dumps(event)}\n\n"
        while True:
            await asyncio.sleep(5)
            yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

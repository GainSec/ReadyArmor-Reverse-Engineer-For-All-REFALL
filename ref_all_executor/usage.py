import json
import os
import time


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "coverage_service", "data")
USAGE_LOG = os.path.join(DATA_DIR, "agent_usage.jsonl")


def _summary(info):
    return {
        "execution_status": info.get("execution_status"),
        "created_at": info.get("created_at"),
        "updated_at": info.get("updated_at"),
        "title": info.get("title"),
        "current_model_id": info.get("current_model_id"),
        "stats": info.get("stats") or {},
    }


def record_and_delete(oh, cid, context, *, log_path=USAGE_LOG):
    row = {"ts": time.time(), "conversation_id": cid, **dict(context)}
    try:
        row.update(_summary(oh.conversation_info(cid)))
    except Exception as exc:
        row["usage_error"] = str(exc)
    finally:
        try:
            oh.delete(cid)
        finally:
            os.makedirs(os.path.dirname(os.fspath(log_path)), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
    return row

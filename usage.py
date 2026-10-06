"""Token usage tracking, persisted to usage.json.

Records every brain call: backend, model, input/output tokens. The dashboard
shows totals so you know how heavily you're using Claude (Pro limits) or
Ollama (free, shown for interest).
"""

import json
import os
import threading
import time

USAGE_FILE = os.path.join(os.path.dirname(__file__), "usage.json")
_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"events": []}


def record(backend: str, model: str, input_tokens: int, output_tokens: int) -> None:
    with _lock:
        data = _load()
        data["events"].append({
            "ts": time.time(),
            "backend": backend,
            "model": model,
            "in": int(input_tokens),
            "out": int(output_tokens),
        })
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)


def summary() -> dict:
    """Aggregated stats for the dashboard: today / last 7 days / all time."""
    with _lock:
        events = _load()["events"]
    import datetime
    now = time.time()
    midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = midnight.timestamp()
    week_start = now - 7 * 86400

    def bucket(since: float) -> dict:
        out: dict = {}
        for e in events:
            if e["ts"] < since:
                continue
            b = out.setdefault(e["backend"], {"requests": 0, "in": 0, "out": 0})
            b["requests"] += 1
            b["in"] += e["in"]
            b["out"] += e["out"]
        return out

    return {
        "today": bucket(day_start),
        "week": bucket(week_start),
        "all_time": bucket(0),
    }

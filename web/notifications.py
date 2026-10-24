from collections import deque
from datetime import datetime

_events = deque(maxlen=200)
_counter = {"id": 0}


def push(title: str, text: str = "", level: str = "info", category: str = "general", url: str = None):
    _counter["id"] += 1
    now = datetime.utcnow()
    _events.append({
        "id": _counter["id"],
        "title": title,
        "text": text,
        "level": level,
        "category": category,
        "url": url,
        "ts": now.strftime("%d.%m %H:%M:%S"),
        "ts_iso": now.isoformat() + "Z",
    })


def since(event_id: int):
    return [e for e in _events if e["id"] > event_id]


def get_all(category: str | None = None):
    if category and category != "all":
        return [e for e in reversed(_events) if e.get("category") == category]
    return list(reversed(_events))

from collections import deque
from datetime import datetime

_events = deque(maxlen=100)
_counter = {"id": 0}


def push(title: str, text: str = "", level: str = "info"):
    _counter["id"] += 1
    _events.append({
        "id": _counter["id"],
        "title": title,
        "text": text,
        "level": level,  # info|warning|success|danger
        "ts": datetime.utcnow().strftime("%H:%M:%S"),
    })


def since(event_id: int):
    return [e for e in _events if e["id"] > event_id]

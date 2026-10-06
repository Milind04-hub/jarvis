"""Timers and reminders that announce themselves out loud when they fire.

A background thread fires each one and calls the announcer callback (set by
the voice loop) so Jarvis speaks the alert. Nothing here blocks.
"""

import threading
import time

_lock = threading.Lock()
_items: dict = {}      # id -> {"timer", "label", "ends", "kind"}
_counter = 0
_announce = None       # callback(str) -> speak it; set via set_announcer


def set_announcer(fn) -> None:
    global _announce
    _announce = fn


def _say(msg: str) -> None:
    if _announce:
        try:
            _announce(msg)
        except Exception:
            pass


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    if s and not h:
        parts.append(f"{s} second" + ("s" if s != 1 else ""))
    return " and ".join(parts) or "0 seconds"


def add_timer(seconds: int, label: str = "") -> str:
    global _counter
    seconds = max(1, int(seconds))
    with _lock:
        _counter += 1
        tid = _counter

    def fire():
        with _lock:
            _items.pop(tid, None)
        name = f"{label} timer" if label else "timer"
        _say(f"Sir, your {name} for {_fmt_duration(seconds)} is up.")

    t = threading.Timer(seconds, fire)
    t.daemon = True
    with _lock:
        _items[tid] = {"timer": t, "label": label or "timer",
                       "ends": time.time() + seconds, "kind": "timer"}
    t.start()
    return f"Timer set for {_fmt_duration(seconds)}."


def add_reminder(seconds: int, text: str) -> str:
    global _counter
    seconds = max(1, int(seconds))
    with _lock:
        _counter += 1
        tid = _counter

    def fire():
        with _lock:
            _items.pop(tid, None)
        _say(f"Reminder, sir: {text}.")

    t = threading.Timer(seconds, fire)
    t.daemon = True
    with _lock:
        _items[tid] = {"timer": t, "label": text, "ends": time.time() + seconds,
                       "kind": "reminder"}
    t.start()
    return f"I'll remind you in {_fmt_duration(seconds)}."


def list_active() -> str:
    with _lock:
        items = list(_items.values())
    if not items:
        return "You have no active timers or reminders."
    now = time.time()
    lines = []
    for it in items:
        left = _fmt_duration(max(0, it["ends"] - now))
        if it["kind"] == "reminder":
            lines.append(f"reminder '{it['label']}' in {left}")
        else:
            lines.append(f"{it['label']} with {left} left")
    return "Active: " + "; ".join(lines) + "."


def cancel_all() -> str:
    with _lock:
        items = list(_items.values())
        _items.clear()
    for it in items:
        it["timer"].cancel()
    return (f"Cancelled {len(items)} timer(s)." if items
            else "There was nothing to cancel.")

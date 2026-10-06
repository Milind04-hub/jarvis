"""Jarvis launcher — voice assistant + web dashboard.

Run this instead of ears.py. It starts the voice loop in a background
thread and serves the control dashboard at http://localhost:7777.
"""

import json
import os
import threading
import time
import urllib.request

from flask import Flask, jsonify, request, send_from_directory

import config
import usage
from ears import Ears

app = Flask(__name__)
ears: Ears | None = None


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/state")
def api_state():
    return jsonify({
        "status": ears.state["status"] if ears else "starting",
        "muted": ears.state["muted"] if ears else False,
        "log": ears.state["log"] if ears else [],
        "settings": {
            "backend": config.BRAIN_BACKEND,
            "fallback": config.BRAIN_FALLBACK,
            "ollama_model": config.OLLAMA_MODEL,
            "claude_model": config.CLAUDE_MODEL,
        },
    })


@app.get("/api/usage")
def api_usage():
    return jsonify(usage.summary())


@app.get("/api/export_pdf")
def api_export_pdf():
    import datetime
    import io

    from fpdf import FPDF
    from flask import send_file

    log = ears.state["log"] if ears else []

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_title("Jarvis Conversation")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Jarvis - Conversation Log", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120)
    stamp = datetime.datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    pdf.cell(0, 8, f"Exported {stamp}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def clean(s: str) -> str:
        return s.encode("latin-1", "replace").decode("latin-1")

    if not log:
        pdf.set_text_color(120)
        pdf.cell(0, 8, "No conversation yet.", new_x="LMARGIN", new_y="NEXT")

    for e in log:
        t = datetime.datetime.fromtimestamp(e["ts"]).strftime("%I:%M %p")
        is_you = e["role"] == "you"
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*(31, 111, 235) if is_you else (40, 40, 40))
        pdf.cell(0, 7, f"{'You' if is_you else 'Jarvis'}  ({t})",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(20)
        pdf.multi_cell(0, 6, clean(e["text"]))
        pdf.ln(2)

    data = bytes(pdf.output())
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"jarvis-chat-{datetime.datetime.now():%Y%m%d-%H%M}.pdf",
    )


@app.get("/api/ollama_models")
def api_ollama_models():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            tags = json.loads(r.read())
        return jsonify([m["name"] for m in tags.get("models", [])])
    except Exception:
        return jsonify([])


@app.post("/api/mute")
def api_mute():
    body = request.get_json(force=True)
    if ears:
        ears.state["muted"] = bool(body.get("muted"))
    return jsonify({"ok": True})


@app.post("/api/settings")
def api_settings():
    body = request.get_json(force=True)
    if body.get("backend") in ("ollama", "claude_code"):
        config.BRAIN_BACKEND = body["backend"]
        config.BRAIN_FALLBACK = (
            "claude_code" if body["backend"] == "ollama" else "ollama"
        )
    if body.get("ollama_model"):
        config.OLLAMA_MODEL = body["ollama_model"]
    if body.get("claude_model") in ("haiku", "sonnet", "opus"):
        config.CLAUDE_MODEL = body["claude_model"]
    return jsonify({"ok": True})


def start_voice_loop() -> None:
    global ears
    ears = Ears()
    ears.run()


# ---------------- system tray ----------------

def _tray_icon_image(muted: bool, busy: bool):
    """Arc-reactor icon matching static/icon.svg.
    Core glow shows status: blue = listening, gold = busy, red = muted."""
    import math

    from PIL import Image, ImageDraw

    core, core_edge = ("#f85149", "#ffb3ad") if muted else (
        ("#d29922", "#ffe19e") if busy else ("#58a6ff", "#bfe3ff"))

    s = 4  # supersample for smooth edges at tray size
    W = 64 * s
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def ring(r, color, width, opacity):
        col = tuple(int(color[i:i+2], 16) for i in (1, 3, 5)) + (int(255 * opacity),)
        d.ellipse([W/2 - r*s, W/2 - r*s, W/2 + r*s, W/2 + r*s],
                  outline=col, width=int(width * s))

    d.ellipse([2*s, 2*s, 62*s, 62*s], fill="#0d1117")
    ring(26, "#1f6feb", 2, 0.55)
    ring(19, "#58a6ff", 2.5, 0.8)
    # segmented ticks
    for angle in range(0, 360, 45):
        a = math.radians(angle)
        x1 = W/2 + math.cos(a) * 16.5*s; y1 = W/2 + math.sin(a) * 16.5*s
        x2 = W/2 + math.cos(a) * 22.5*s; y2 = W/2 + math.sin(a) * 22.5*s
        d.line([x1, y1, x2, y2], fill="#9ecbff", width=4*s)
    # glowing core (status color)
    d.ellipse([W/2 - 11*s, W/2 - 11*s, W/2 + 11*s, W/2 + 11*s], fill=core)
    d.ellipse([W/2 - 6*s, W/2 - 6*s, W/2 + 6*s, W/2 + 6*s], fill=core_edge)
    ring(11, core_edge, 1.5, 0.9)

    return img.resize((64, 64), Image.LANCZOS)


window = None  # the pywebview desktop window


def run_tray() -> None:
    """System-tray icon. Runs on a background thread; controls the window."""
    import pystray

    def is_muted() -> bool:
        return bool(ears and ears.state["muted"])

    def is_busy() -> bool:
        return bool(ears and ears.state["status"] in
                    ("recording", "transcribing", "thinking", "speaking"))

    def toggle_mute(icon, item) -> None:
        if ears:
            ears.state["muted"] = not ears.state["muted"]

    def show_window(icon, item) -> None:
        if window:
            window.show()
            window.restore()

    def quit_app(icon, item) -> None:
        icon.stop()
        os._exit(0)

    icon = pystray.Icon(
        "jarvis",
        _tray_icon_image(False, False),
        "Jarvis",
        menu=pystray.Menu(
            pystray.MenuItem("Show Jarvis", show_window, default=True),
            pystray.MenuItem("Muted", toggle_mute, checked=lambda item: is_muted()),
            pystray.MenuItem("Quit Jarvis", quit_app),
        ),
    )

    def refresh_icon() -> None:
        last = None
        while True:
            state = (is_muted(), is_busy())
            if state != last:
                icon.icon = _tray_icon_image(*state)
                icon.title = "Jarvis — " + (
                    "muted" if state[0] else ("busy" if state[1] else "listening")
                )
                last = state
            time.sleep(1)

    threading.Thread(target=refresh_icon, daemon=True).start()
    icon.run()


def _wait_for_server() -> None:
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:7777/api/state", timeout=1)
            return
        except Exception:
            time.sleep(0.2)


if __name__ == "__main__":
    import webview

    # give the app its own taskbar identity so it doesn't borrow python's icon
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("jarvis.voice.assistant")

    threading.Thread(target=start_voice_loop, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=7777, debug=False),
        daemon=True,
    ).start()
    threading.Thread(target=run_tray, daemon=True).start()

    _wait_for_server()

    # Closing the window hides it to the tray instead of quitting.
    def on_closing():
        window.hide()
        return False  # cancel the close

    window = webview.create_window(
        "Jarvis",
        "http://127.0.0.1:7777",
        width=920,
        height=760,
        background_color="#0d1117",
    )
    window.events.closing += on_closing
    icon_path = os.path.join(os.path.dirname(__file__), "static", "icon.ico")
    webview.start(icon=icon_path)  # blocks on main thread until the app quits

"""Phase 3 — Jarvis's brain.

Two backends, order controlled by config.BRAIN_BACKEND / BRAIN_FALLBACK:

- "ollama"      — local model, fastest responses, free.
- "claude_code" — Claude via your Pro subscription (claude -p headless).
                  Runs in an empty workspace dir with a fast model so it
                  doesn't waste time reading project files.

If the primary backend fails, the other is tried automatically.
"""

import glob
import json
import os
import shutil
import subprocess
import urllib.request

import config
import tools
import usage

SYSTEM_PROMPT = (
    "You are Jarvis, a sharp and capable voice assistant modeled on Tony "
    "Stark's AI. You are confident, witty, and concise — never rambling. "
    "Your replies are spoken aloud, so: be brief (1-3 sentences unless asked "
    "for detail), use plain spoken language, no markdown, no code blocks, no "
    "bullet points, no emoji. Write numbers and units naturally for speech. "
    "If you don't know something or it requires live data you don't have, say "
    "so plainly rather than guessing. Address the user as 'sir' occasionally, "
    "not every time. "
    "You cannot open browser tabs yourself; if the user wants pages opened, "
    "tell them to say 'look up' followed by the topic. "
    "Reply in the same language the user spoke: if they speak Hindi, reply in "
    "natural Hindi using Devanagari script; if English, reply in English. "
    "CRITICAL: never claim you did something — set a timer, opened tabs, got "
    "the weather or news, started music — unless you actually call the matching "
    "tool in this turn. Do not invent or template results. If a task needs a "
    "tool, call it; only describe the outcome after the tool returns."
)


def _system_prompt() -> str:
    import datetime
    now = datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
    return SYSTEM_PROMPT + f" The current date and time is {now}."


def _find_claude() -> str | None:
    """Locate the Claude Code CLI: PATH first, then the desktop app bundle."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    bundled = glob.glob(
        os.path.expandvars(
            r"%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude"
            r"\claude-code\*\claude.exe"
        )
    )
    return max(bundled) if bundled else None  # newest version


class Brain:
    def __init__(self) -> None:
        self.claude_path = _find_claude()
        self.first_turn = True
        self.history: list[dict] = []  # ollama conversation memory
        # empty workspace so claude -p doesn't scan the jarvis project
        self.claude_cwd = os.path.join(os.path.dirname(__file__), ".brain_workspace")
        os.makedirs(self.claude_cwd, exist_ok=True)
        order = [config.BRAIN_BACKEND, config.BRAIN_FALLBACK]
        self.backends = [b for b in dict.fromkeys(order) if b]
        print(f"Brain: {' -> '.join(self.backends)}"
              + ("" if self.claude_path else " (claude CLI not found)"))
        if "ollama" in self.backends:
            self._warm_up_ollama()

    def _warm_up_ollama(self) -> None:
        """Load the model into RAM in the background so turn one is fast."""
        import threading

        def warm():
            try:
                req = urllib.request.Request(
                    "http://localhost:11434/api/generate",
                    data=json.dumps({
                        "model": config.OLLAMA_MODEL,
                        "keep_alive": "30m",
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=300).read()
                print("[brain] ollama model warmed up")
            except Exception:
                pass  # ollama not running; claude fallback will cover it

        threading.Thread(target=warm, daemon=True).start()

    def ask(self, text: str) -> str:
        errors = []
        # read config live so the dashboard can switch backends at runtime
        order = [config.BRAIN_BACKEND, config.BRAIN_FALLBACK]
        self.backends = [b for b in dict.fromkeys(order) if b]
        for backend in self.backends:
            try:
                if backend == "ollama":
                    return self._ask_ollama(text)
                if backend == "claude_code" and self.claude_path:
                    return self._ask_claude(text)
            except Exception as e:
                errors.append(f"{backend}: {e}")
                print(f"[brain] {backend} failed — trying next backend")
        print(f"[brain] all backends failed: {errors}")
        return "Sorry, my brain is unreachable right now."

    def _ask_claude(self, text: str) -> str:
        cmd = [
            self.claude_path, "-p", text,
            "--append-system-prompt", _system_prompt(),
            "--model", config.CLAUDE_MODEL,
            "--output-format", "json",
        ]
        if not self.first_turn:
            cmd.append("--continue")  # stay in the same conversation
        # CREATE_NO_WINDOW: don't flash a console window on each call (Windows)
        no_window = 0x08000000 if os.name == "nt" else 0
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8",
            timeout=config.BRAIN_TIMEOUT, stdin=subprocess.DEVNULL,
            cwd=self.claude_cwd,
            creationflags=no_window,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        data = json.loads(result.stdout)
        if data.get("is_error"):
            raise RuntimeError(data.get("result", "unknown claude error"))
        self.first_turn = False
        u = data.get("usage", {})
        usage.record(
            "claude", config.CLAUDE_MODEL,
            u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0),
            u.get("output_tokens", 0),
        )
        return data["result"].strip()

    def _ollama_chat(self, messages: list, use_tools: bool) -> dict:
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep model in RAM between questions
            "options": {"temperature": 0.3},  # lower = more reliable tool calls
        }
        if use_tools:
            enabled = {
                "web_search": config.WEB_SEARCH_ENABLED,
                # the model must NOT open tabs on its own — only the "look up"
                # phrase does that (handled deterministically in ears.py)
                "open_tabs": False,
            }
            schema = [t for t in tools.TOOLS_SCHEMA
                      if enabled.get(t["function"]["name"], True)]
            if schema:
                payload["tools"] = schema
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=config.BRAIN_TIMEOUT) as resp:
            body = json.loads(resp.read())
        usage.record(
            "ollama", config.OLLAMA_MODEL,
            body.get("prompt_eval_count", 0),
            body.get("eval_count", 0),
        )
        return body

    def _ask_ollama(self, text: str) -> str:
        messages = (
            [{"role": "system", "content": _system_prompt()}]
            + self.history[-config.OLLAMA_HISTORY_TURNS * 2:]
            + [{"role": "user", "content": text}]
        )
        # up to 3 rounds so the model can search, then answer
        for _ in range(3):
            body = self._ollama_chat(messages, use_tools=True)
            msg = body["message"]
            calls = msg.get("tool_calls")
            if not calls:
                break
            messages.append(msg)  # the assistant's tool-call request
            for call in calls:
                fn = call["function"]
                name = fn["name"]
                args = fn.get("arguments", {})
                print(f"[tool] {name}({args})")
                func = tools.DISPATCH.get(name)
                output = func(**args) if func else f"Unknown tool: {name}"
                messages.append({"role": "tool", "name": name, "content": output})

        reply = msg.get("content", "").strip()
        self.history += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply},
        ]
        return reply

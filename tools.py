"""Phase 4 — Jarvis's tools.

Capabilities the brain can call:
- web_search: DuckDuckGo lookup (free, no API key).
- open_tabs: open relevant web pages in the default browser.

Each tool has an OpenAI/Ollama-style schema so the local model can invoke
it through Ollama's function-calling support.
"""

import ctypes
import datetime
import os
import urllib.parse
import urllib.request
import webbrowser
from urllib.parse import quote_plus, urlparse

from ddgs import DDGS

import config
import timers

MAX_TABS = 5  # safety cap on how many tabs one request may open


def _ascii(text: str) -> str:
    """Strip chars the Windows console/TTS can't handle, to avoid crashes."""
    return text.encode("ascii", "ignore").decode("ascii")


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web; return a compact summary including each result's URL."""
    # a new lookup means the previous topic's PAGE windows are stale — clear
    # them (music windows are left playing)
    try:
        import tiler
        if tiler._opened:
            tiler.close_pages()
    except Exception:
        pass
    try:
        results = list(DDGS().text(query, max_results=max_results))
    except Exception as e:
        return f"Search failed: {e}"
    if not results:
        return "No results found."
    lines = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        url = r.get("href", "")
        lines.append(f"- {title} ({url}): {body}")
    return _ascii("\n".join(lines))


def open_tabs(urls=None, search_query: str = "", include_video: bool = True) -> str:
    """Open web pages in the default browser.

    Pass `urls` (specific http/https links) and/or `search_query` (resolved to
    specific article pages from distinct sources, plus one relevant video when
    `include_video` is true). Only safe web links are opened; local files and
    other schemes are rejected.
    """
    if not config.OPEN_TABS_ENABLED:
        return "Opening tabs is disabled in settings."

    to_open = []
    if isinstance(urls, str):
        urls = [urls]
    for u in (urls or []):
        parsed = urlparse(u.strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            to_open.append(u.strip())

    # Resolve a query to specific content pages (not a search-results page).
    if search_query:
        to_open += _resolve_pages(search_query, include_video)

    # de-dupe while preserving order, then cap
    seen, deduped = set(), []
    for u in to_open:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    deduped = deduped[:MAX_TABS]

    if not deduped:
        return "No valid web links to open."

    # tile into separate windows if enabled and there's more than one page
    if config.TILE_WINDOWS and len(deduped) > 1:
        try:
            import tiler
            if tiler.open_tiled(deduped):
                return f"Opened {len(deduped)} tiled windows: " + ", ".join(deduped)
        except Exception as e:
            print(f"[tiler] failed ({e}); opening as tabs instead")

    for u in deduped:
        webbrowser.open_new_tab(u)
    return f"Opened {len(deduped)} tab(s): " + ", ".join(deduped)


def _resolve_pages(query: str, include_video: bool) -> list:
    """Pick specific article pages (distinct sources) + one relevant video."""
    pages: list = []

    # specific articles: prefer news results (real article URLs)
    try:
        hits = list(DDGS().news(query, max_results=6))
    except Exception:
        hits = []
    if not hits:  # fall back to general text results
        try:
            hits = [{"url": h.get("href")} for h in
                    DDGS().text(query, max_results=6)]
        except Exception:
            hits = []
    seen_domains = set()
    for h in hits:
        url = h.get("url")
        if not url:
            continue
        domain = urlparse(url).netloc.replace("www.", "")
        if domain and domain not in seen_domains and _is_specific(url):
            seen_domains.add(domain)
            pages.append(url)
        if len(pages) >= 2:  # two distinct sources
            break

    # one relevant video
    if include_video:
        try:
            for v in DDGS().videos(query, max_results=3):
                content = v.get("content") or v.get("embed_url")
                if content and content.startswith("http"):
                    pages.append(content)
                    break
        except Exception:
            pass

    if not pages:  # nothing resolved — fall back to a search page
        pages.append("https://duckduckgo.com/?q=" + quote_plus(query))
    return pages


def _is_specific(url: str) -> bool:
    """True if the URL points at a specific page, not a site homepage/index."""
    path = urlparse(url).path.strip("/")
    return len(path) > 3  # has a real slug, not just '/' or '/news'


# Schemas advertised to the model
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current, real-time, or factual information "
                "the assistant may not know: news, weather, prices, sports "
                "scores, recent events, or anything that may have changed since "
                "training. Use this whenever the user asks about something "
                "current or time-sensitive."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_tabs",
            "description": (
                "Open relevant web pages in the user's browser when they ask "
                "you to open, show, pull up, bring up, or look at something — "
                "e.g. 'open the news about X', 'pull up the recipe', 'show me "
                "the Eiffel Tower', 'open YouTube'. Easiest usage: just pass a "
                "'search_query' describing what they want and the actual top "
                "pages will open automatically — you do not need a direct link. "
                "Optionally pass specific 'urls' if you already have them. Call "
                "this immediately whenever the user wants something opened on "
                "screen; do not only search and read it aloud."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific http/https links to open.",
                    },
                    "search_query": {
                        "type": "string",
                        "description": (
                            "What to open. Resolved to specific article pages "
                            "from different sources plus a relevant video."
                        ),
                    },
                    "include_video": {
                        "type": "boolean",
                        "description": (
                            "Whether to also open a relevant video. Default "
                            "true; set false if the user only wants to read."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_tabs",
            "description": (
                "Close all the browser windows you previously opened. Call this "
                "when the user says to close the tabs, close the windows, close "
                "everything, or clear the screen."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                "Launch/open an application by name, e.g. 'open Spotify', "
                "'launch Chrome', 'open calculator'. Pass just the app name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "App name, e.g. 'spotify'."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": (
                "Close/quit a running application by name, e.g. 'close Spotify', "
                "'quit Chrome'. Pass just the app name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "App name, e.g. 'spotify'."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Get the current weather. Pass a city/location, or leave empty "
                "for the user's current location. Use for any weather question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City or place; optional."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_briefing",
            "description": (
                "Give a briefing: current date and time, weather, and top news "
                "headlines. Use for 'morning briefing', 'brief me', 'what's "
                "going on', or 'catch me up'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City for weather; optional."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": (
                "Play a song, artist, or video. Opens the top YouTube result, "
                "which autoplays. Use for 'play X', 'put on some X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Song, artist, or what to play."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": (
                "Control whatever is currently playing with media keys. Action "
                "must be one of: play_pause, next, previous, stop. Use for "
                "'pause', 'resume', 'skip', 'next song', 'go back'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play_pause", "next", "previous", "stop"],
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": (
                "Set a countdown timer. Convert the requested duration to total "
                "seconds (e.g. 10 minutes = 600). Jarvis announces it out loud "
                "when it finishes. Optional label like 'pasta' or 'tea'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Total seconds."},
                    "label": {"type": "string", "description": "Optional name."},
                },
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Remind the user of something after a delay. Convert the delay "
                "to total seconds from now (use the current time given in your "
                "instructions for absolute times like '5pm'). Jarvis speaks the "
                "reminder out loud when it fires."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Seconds from now."},
                    "text": {"type": "string", "description": "What to remind about."},
                },
                "required": ["seconds", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_timers",
            "description": "List active timers and reminders and their time left.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timers",
            "description": "Cancel all active timers and reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

def close_tabs() -> str:
    """Close all the windows/tabs Jarvis previously opened."""
    try:
        import tiler
        n = tiler.close_all()
    except Exception as e:
        return f"Couldn't close windows: {e}"
    return f"Closed {n} window(s)." if n else "There were no open windows to close."


# common app name -> process image name(s) for closing
_APP_PROCESSES = {
    "spotify": ["Spotify.exe"],
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "youtube": ["msedge.exe", "chrome.exe"],
    "notepad": ["notepad.exe"],
    "calculator": ["CalculatorApp.exe", "Calculator.exe"],
    "spotify music": ["Spotify.exe"],
}

# app name -> launch target (URI scheme or executable/alias)
_APP_LAUNCH = {
    "spotify": "spotify:",
    "spotify music": "spotify:",
    "chrome": "chrome",
    "edge": "microsoft-edge:",
    "notepad": "notepad",
    "calculator": "calc",
    "settings": "ms-settings:",
    "explorer": "explorer",
    "file explorer": "explorer",
}


def open_app(name: str) -> str:
    """Launch an application by name (e.g. 'spotify', 'chrome')."""
    import subprocess
    key = name.strip().lower()
    target = _APP_LAUNCH.get(key, key)
    try:
        os.startfile(target)  # works for URI schemes and known executables
        return f"Opening {name}."
    except Exception:
        try:
            # let the shell resolve app execution aliases / PATH
            subprocess.Popen(["cmd", "/c", "start", "", target],
                             creationflags=0x08000000)
            return f"Opening {name}."
        except Exception as e:
            return f"Couldn't open {name}: {e}"


def close_app(name: str) -> str:
    """Close a running application by name (e.g. 'spotify')."""
    import subprocess
    key = name.strip().lower()
    procs = _APP_PROCESSES.get(key, [f"{key}.exe"])
    closed = False
    for p in procs:
        r = subprocess.run(["taskkill", "/IM", p, "/F"],
                           capture_output=True, text=True,
                           creationflags=0x08000000)
        if r.returncode == 0:
            closed = True
    return f"Closed {name}." if closed else f"{name} doesn't seem to be running."


# ---------------- weather & briefing ----------------

def get_weather(location: str = "") -> str:
    """Current weather via wttr.in (free, no API key)."""
    loc = urllib.parse.quote(location.strip())
    where = f"{location.strip()}: " if location.strip() else ""
    url = f"https://wttr.in/{loc}?format=%C,+%t,+feels+like+%f,+wind+%w&m"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return _ascii(where + r.read().decode("utf-8").strip())
    except Exception as e:
        return f"Couldn't get the weather: {e}"


def get_briefing(location: str = "") -> str:
    """A spoken briefing: date/time, weather, and top news headlines."""
    now = datetime.datetime.now().strftime("%A, %B %d, %I:%M %p").replace(" 0", " ")
    weather = get_weather(location)
    headlines = []
    try:
        for h in DDGS().news("top news headlines today", max_results=3):
            if h.get("title"):
                headlines.append(h["title"])
    except Exception:
        pass
    parts = []
    if now:
        parts.append(f"It's {now}.")
    parts.append(f"Weather: {weather}.")
    if headlines:
        parts.append("Top headlines: " + "; ".join(headlines) + ".")
    return _ascii(" ".join(parts))


# ---------------- music & media ----------------

_MEDIA_VK = {
    "play_pause": 0xB3, "pause": 0xB3, "play": 0xB3,
    "next": 0xB0, "skip": 0xB0,
    "previous": 0xB1, "back": 0xB1,
    "stop": 0xB2,
}


_last_player = None  # 'spotify' or 'youtube' — where media controls should go


def play_music(query: str, service: str = "youtube") -> str:
    """Play music. service='spotify' opens Spotify; otherwise YouTube."""
    global _last_player
    _last_player = service
    if service == "spotify":
        return _play_spotify(query)

    url = _youtube_top(query)
    if not url:  # fall back to a YouTube search page the user can click
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    try:
        import tiler
        tiler.open_music(url)  # tracked so 'close all' can stop it
    except Exception:
        webbrowser.open_new_tab(url)
    return f"Playing {query}."


def _play_spotify(query: str) -> str:
    """Play on Spotify via the Web API if set up; else open the app to search."""
    try:
        import spotify
        if spotify.is_configured():
            return spotify.play(query)
    except Exception:
        pass
    # not set up yet — fall back to opening the app at the search
    try:
        os.startfile(f"spotify:search:{query}")
        return f"Opening {query} on Spotify. Press play, or set up full control to autoplay."
    except Exception:
        webbrowser.open_new_tab("https://open.spotify.com/search/" + quote_plus(query))
        return f"Opening {query} on Spotify in your browser."


def _youtube_top(query: str) -> str | None:
    """Resolve a music query to YouTube's top OFFICIAL result (region-correct)."""
    # bias toward official uploads: correct artist, reliably available
    for q in (f"{query} official audio", query):
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{q}", download=False)
            entries = info.get("entries") or []
            if entries and entries[0].get("id"):
                return "https://www.youtube.com/watch?v=" + entries[0]["id"]
        except Exception:
            continue
    return None


def media_control(action: str) -> str:
    """Control playback. Routes to whatever Jarvis last played: the Spotify
    API if that was Spotify, otherwise a system media key (YouTube etc.)."""
    action = action.lower().replace(" ", "_")
    # send to Spotify's API when Spotify is the active player
    try:
        import spotify
        if _last_player == "spotify" and spotify.is_configured():
            return spotify.control(action)
        # also use Spotify if it's the one actually playing right now
        if spotify.is_configured():
            pb = spotify._get_client().current_playback()
            if pb and pb.get("is_playing"):
                return spotify.control(action)
    except Exception:
        pass
    vk = _MEDIA_VK.get(action)
    if vk is None:
        return f"I don't know the media action '{action}'."
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    return f"Done: {action}."


# ---------------- timers & reminders ----------------

def set_timer(seconds: int, label: str = "") -> str:
    return timers.add_timer(seconds, label)


def set_reminder(seconds: int, text: str = "") -> str:
    return timers.add_reminder(seconds, text)


def list_timers() -> str:
    return timers.list_active()


def cancel_timers() -> str:
    return timers.cancel_all()


# name -> callable
DISPATCH = {
    "web_search": web_search,
    "open_tabs": open_tabs,
    "close_tabs": close_tabs,
    "open_app": open_app,
    "close_app": close_app,
    "get_weather": get_weather,
    "get_briefing": get_briefing,
    "play_music": play_music,
    "media_control": media_control,
    "set_timer": set_timer,
    "set_reminder": set_reminder,
    "list_timers": list_timers,
    "cancel_timers": cancel_timers,
}

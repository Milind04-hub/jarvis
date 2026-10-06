"""Spotify playback control via the Web API (requires Premium).

Setup is one-time:
1. Create an app at https://developer.spotify.com/dashboard
2. Add redirect URI  http://127.0.0.1:8888/callback
3. Put the Client ID/Secret in spotify_config.json (see template)
4. Run:  .venv\\Scripts\\python.exe setup_spotify.py   (authorize in browser once)

After that, playback works hands-free. Tokens are cached in .spotify_cache.
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "spotify_config.json")
CACHE_PATH = os.path.join(os.path.dirname(__file__), ".spotify_cache")
SCOPE = "user-modify-playback-state user-read-playback-state"

_client = None  # cached spotipy client


def _load_config() -> dict | None:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("client_id") and cfg.get("client_secret"):
            return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _auth_manager(open_browser: bool):
    import spotipy
    cfg = _load_config()
    if not cfg:
        return None
    return spotipy.oauth2.SpotifyOAuth(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=cfg.get("redirect_uri", "http://127.0.0.1:8888/callback"),
        scope=SCOPE,
        cache_path=CACHE_PATH,
        open_browser=open_browser,
    )


def is_configured() -> bool:
    return _load_config() is not None and os.path.exists(CACHE_PATH)


def _get_client():
    global _client
    if _client is not None:
        return _client
    import spotipy
    auth = _auth_manager(open_browser=False)
    if not auth:
        return None
    # requests_timeout so a network hiccup can't freeze Jarvis; retries=0
    _client = spotipy.Spotify(auth_manager=auth, requests_timeout=8, retries=0)
    return _client


def authorize() -> None:
    """One-time interactive login (run from setup_spotify.py)."""
    auth = _auth_manager(open_browser=True)
    if not auth:
        raise RuntimeError("Fill in spotify_config.json first.")
    auth.get_access_token(as_dict=False)  # opens browser, caches token


def _ensure_device(sp) -> str | None:
    """Return an active device id, launching the Spotify app if needed."""
    import time
    devices = sp.devices().get("devices", [])
    if devices:
        active = next((d for d in devices if d["is_active"]), devices[0])
        return active["id"]
    # no device — open the desktop app and wait for it to register
    try:
        os.startfile("spotify:")
    except Exception:
        pass
    for _ in range(15):
        time.sleep(1)
        devices = sp.devices().get("devices", [])
        if devices:
            return devices[0]["id"]
    return None


def _clean_query(query: str) -> str:
    """Spotify search ranks badly on filler words — strip them. 'by' is the
    worst offender (searched literally), so drop it and similar connectors."""
    import re
    q = re.sub(r"\b(by|the song|a song|song|track|please)\b", " ", query,
               flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip() or query


def play(query: str) -> str:
    sp = _get_client()
    if not sp:
        return "Spotify isn't set up yet."
    try:
        # NOTE: limit=1 makes Spotify return a worse-ranked result than
        # limit>=2 (a real API quirk), so ask for several and take the top.
        results = sp.search(q=_clean_query(query), type="track", limit=5)
        items = results["tracks"]["items"]
        if not items:
            return f"Couldn't find {query} on Spotify."
        track = items[0]
        device_id = _ensure_device(sp)
        if not device_id:
            return "Open Spotify on a device first, then try again."
        # Build a queue so 'next' works. Spotify blocks recommendations/top-
        # tracks for new apps, so play the song within its album (next = next
        # album track); fall back to the other search hits, then a single track.
        album = track.get("album", {})
        try:
            if album.get("uri") and album.get("total_tracks", 1) > 1:
                sp.start_playback(device_id=device_id,
                                  context_uri=album["uri"],
                                  offset={"uri": track["uri"]})
            else:
                sp.start_playback(device_id=device_id,
                                  uris=[t["uri"] for t in items])
        except Exception:
            sp.start_playback(device_id=device_id, uris=[track["uri"]])
        return f"Playing {track['name']} by {track['artists'][0]['name']} on Spotify."
    except Exception as e:
        return f"Spotify playback failed: {e}"


def control(action: str) -> str:
    sp = _get_client()
    if not sp:
        return "Spotify isn't set up yet."
    try:
        if action in ("pause", "play_pause"):
            playback = sp.current_playback()
            if playback and playback.get("is_playing"):
                sp.pause_playback()
                return "Paused."
            sp.start_playback()
            return "Resumed."
        if action in ("next", "skip"):
            sp.next_track()
            return "Skipped."
        if action in ("previous", "back"):
            sp.previous_track()
            return "Previous track."
        return f"Unknown action: {action}"
    except Exception as e:
        return f"Spotify control failed: {e}"

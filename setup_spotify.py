"""One-time Spotify authorization. Run once after filling spotify_config.json:

    .venv\\Scripts\\python.exe setup_spotify.py

A browser window opens — log in and click Agree. After that, Jarvis can
control Spotify playback hands-free.
"""

import spotify

if __name__ == "__main__":
    if not spotify._load_config():
        print("ERROR: fill in client_id and client_secret in spotify_config.json first.")
        raise SystemExit(1)
    print("Opening browser to authorize Spotify...")
    spotify.authorize()
    print("Done! Spotify is now connected. You can close this window.")

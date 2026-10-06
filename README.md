# Jarvis

A privacy-first voice assistant for Windows, powered by local AI (OpenWakeWord + Whisper + Qwen). It controls Spotify, searches the web, sets timers and opens apps hands-free, with a live dashboard and English/Hindi support.

## Features

- **Wake word**: say "hey jarvis" to start a conversation, "roger that" to end it. Saying "hey jarvis" while it's talking interrupts it.
- **Local brain**: Qwen2.5 14B through Ollama on your GPU. Claude (via the Claude Code CLI) is the fallback.
- **Speech**: Whisper large-v3 on the GPU understands English, Hindi and Hinglish. Piper TTS replies in an English or Hindi voice.
- **Web**: live search through DuckDuckGo. "Look up X" opens articles and a video as tiled windows.
- **Music**: "play X" uses YouTube, "play X on Spotify" uses Spotify. Pause, resume, skip and previous all work by voice.
- **Utilities**: weather, a spoken briefing, timers and reminders, and opening or closing apps.
- **Desktop app**: a native window and a tray icon. The dashboard lets you switch models, see token usage and export the chat as a PDF.

## Voice commands

| Say | Does |
|---|---|
| `hey jarvis` | Wake up, or interrupt |
| `look up <topic>` | Open tiled articles and a video |
| `play <song> [on spotify]` | Play music |
| `pause` / `resume` / `skip` / `go back` | Control playback |
| `open <app>` / `close <app>` | Launch or quit an app |
| `close all tabs` | Close the windows Jarvis opened |
| `brief me` | Date, weather and headlines |
| `set a 10 minute timer` / `remind me in...` | Timers and reminders |
| `roger that` | Go back to sleep |

## Setup

Requires Windows, Python 3.12+, [Ollama](https://ollama.com) and ideally an NVIDIA GPU.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
ollama pull qwen2.5:14b
.venv\Scripts\python -m piper.download_voices en_GB-alan-medium --data-dir voices
.venv\Scripts\python -m piper.download_voices hi_IN-rohan-medium --data-dir voices
```

To run it, double-click `Jarvis.bat` or run `.venv\Scripts\python app.py`.

### Spotify (optional, requires Premium)

1. Create an app at https://developer.spotify.com/dashboard with the redirect URI `http://127.0.0.1:8888/callback`.
2. Copy `spotify_config.example.json` to `spotify_config.json` and fill in your keys.
3. Run `.venv\Scripts\python setup_spotify.py` once to authorize.

## Configuration

All settings live in `config.py`: models, wake threshold, silence timing, voices and feature toggles.

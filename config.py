"""Central configuration for Jarvis."""

# --- Audio ---
SAMPLE_RATE = 16000          # required by openWakeWord and Silero VAD
CHUNK_SIZE = 1280            # 80 ms frames (openWakeWord's expected frame size)

# --- Wake word ---
WAKE_MODEL = "hey_jarvis_v0.1"   # say "hey jarvis"
WAKE_THRESHOLD = 0.65            # 0..1, raise if false triggers, lower if it misses you
INTERRUPT_THRESHOLD = 0.35       # lower bar to catch "hey jarvis" over his own speech

# --- Conversation mode ---
STOP_PHRASES = ["roger that", "roger dad"]  # second one: common mishearing
CLOSE_PHRASES = [               # handled in code, not by the model, for reliability
    "close all tabs", "close the tabs", "close tabs", "close all windows",
    "close the windows", "close all the tabs", "close everything",
    "clear the screen", "close the tab",
]
BRIEFING_PHRASES = [           # handled in code so the briefing is never faked
    "brief me", "briefing", "catch me up", "whats going on", "what's going on",
    "morning briefing", "give me the rundown", "fill me in",
]
DEFAULT_LOCATION = ""          # city for weather; empty = auto-detect by IP
CONVERSATION_MAX_IDLE_ROUNDS = 6  # empty listens (~4s each) before auto-sleep

# --- Command recording (after wake word) ---
VAD_THRESHOLD = 0.3          # Silero VAD speech probability threshold (lower = more sensitive to quiet speech)
SILENCE_DURATION = 2.0       # seconds of silence that ends the command — your thinking-pause budget
MAX_COMMAND_SECONDS = 30     # hard cap on a single command
MIN_COMMAND_SECONDS = 0.4    # ignore recordings shorter than this (false trigger)

RECORDINGS_DIR = "recordings"

# --- Speech-to-text (Phase 2) ---
WHISPER_MODEL = "large-v3"   # multilingual, GPU; best Hindi/Hinglish accuracy
WHISPER_CPU_FALLBACK = "small"  # used if the GPU isn't usable (faster on CPU)
WHISPER_LANGUAGE = None      # None = auto-detect language per utterance (English, Hindi, mixed)

# --- Brain (Phase 3) ---
# "ollama"       -> local model, fastest responses, free
# "claude_code"  -> Claude via your Pro subscription, smarter but slower
# Primary backend is tried first; on failure the fallback is used.
BRAIN_BACKEND = "ollama"
BRAIN_FALLBACK = "claude_code"
OLLAMA_MODEL = "qwen2.5:14b"  # strong + current, fits your 16GB RTX 5070 Ti; "llama3.2:3b" = fast backup
OLLAMA_HISTORY_TURNS = 10    # conversation turns Ollama remembers
CLAUDE_MODEL = "haiku"       # haiku = fastest; or "sonnet"
BRAIN_TIMEOUT = 120  # seconds

# --- Tools (Phase 4) ---
WEB_SEARCH_ENABLED = True    # let Jarvis look things up live via DuckDuckGo (free)
OPEN_TABS_ENABLED = True      # let Jarvis open relevant web pages in your browser
TILE_WINDOWS = True           # open pages as separate tiled windows (vs. tabs in one window)

# --- Text-to-speech (Phase 3) ---
TTS_VOICE = "en_GB-alan-medium"  # British male; see https://rhasspy.github.io/piper-samples/
TTS_VOICE_HINDI = "hi_IN-rohan-medium"  # used automatically when Jarvis replies in Hindi

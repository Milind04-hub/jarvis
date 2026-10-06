"""Phase 1 — Jarvis's ears.

Listens to the microphone continuously. When it hears "hey jarvis", it beeps,
records your command until you stop talking (Silero VAD), and saves it as a
WAV file in recordings/. Later phases feed that audio to speech-to-text.

Run:  .venv\\Scripts\\python.exe ears.py
"""

import os
import queue
import time
import wave

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

import config


def beep(listening: bool) -> None:
    """Audio cue: a smooth 'blooop' — pitch slides up = listening, down = done."""
    sr = 44100
    dur = 0.28
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    f0, f1 = (300, 750) if listening else (750, 300)
    # exponential pitch glide, integrated for a smooth sweep
    freq = f0 * (f1 / f0) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase)
    # rounded envelope: soft attack, gentle release
    envelope = np.sin(np.pi * t / dur) ** 1.5
    sd.play((0.4 * tone * envelope).astype(np.float32), samplerate=sr, blocking=True)


def save_wav(audio: np.ndarray, path: str) -> None:
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)  # int16
        f.setframerate(config.SAMPLE_RATE)
        f.writeframes(audio.tobytes())


class Ears:
    def __init__(self) -> None:
        from transcriber import Transcriber
        from brain import Brain
        from voice import Voice
        # shared state, read by the web dashboard
        self.state: dict = {"status": "starting", "log": [], "muted": False}
        self.transcriber = Transcriber()
        self.brain = Brain()
        self.voice = Voice()
        # let timers/reminders speak through Jarvis's voice when they fire
        import timers
        timers.set_announcer(self._announce)
        print("Loading wake-word model...")
        self.oww = Model(
            wakeword_models=[config.WAKE_MODEL],
            inference_framework="onnx",
            vad_threshold=0,  # we run VAD ourselves during command capture
        )
        # openWakeWord ships a Silero VAD wrapper; reuse it for end-of-speech
        from openwakeword.vad import VAD
        self.vad = VAD()
        self.audio_q: queue.Queue[np.ndarray] = queue.Queue()
        os.makedirs(config.RECORDINGS_DIR, exist_ok=True)

    def _log(self, role: str, text: str) -> None:
        self.state["log"].append({"ts": time.time(), "role": role, "text": text})
        del self.state["log"][:-100]  # keep last 100 entries

    def _announce(self, text: str) -> None:
        """Speak a timer/reminder alert (called from a background thread)."""
        self._log("jarvis", text)
        self.voice.say(text)

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio warning] {status}")
        self.audio_q.put(indata[:, 0].copy())

    def record_command(self) -> np.ndarray | None:
        """Record until SILENCE_DURATION of no speech, or MAX_COMMAND_SECONDS."""
        frames: list[np.ndarray] = []
        last_speech = time.monotonic()
        started = last_speech
        heard_speech = False

        while True:
            chunk = self.audio_q.get()
            frames.append(chunk)
            now = time.monotonic()

            speech_prob = self.vad.predict(chunk)
            if speech_prob >= config.VAD_THRESHOLD:
                last_speech = now
                heard_speech = True

            if now - started > config.MAX_COMMAND_SECONDS:
                break
            if heard_speech and now - last_speech > config.SILENCE_DURATION:
                break
            if not heard_speech and now - started > 4:
                return None  # wake word fired but nobody spoke

        audio = np.concatenate(frames)
        if len(audio) / config.SAMPLE_RATE < config.MIN_COMMAND_SECONDS:
            return None
        return audio

    def _drain_queue(self) -> None:
        while not self.audio_q.empty():
            self.audio_q.get_nowait()

    def speak_interruptible(self, text: str) -> bool:
        """Speak, but keep watching the mic: saying 'hey jarvis' cuts him off.
        Returns True if interrupted."""
        result = self.voice.synth(text)
        if result is None:
            return False
        audio, sr = result
        self._drain_queue()
        self.oww.reset()
        sd.play(audio, samplerate=sr)  # non-blocking
        deadline = time.monotonic() + len(audio) / sr
        try:
            while time.monotonic() < deadline:
                try:
                    chunk = self.audio_q.get(timeout=0.2)
                except queue.Empty:
                    continue
                score = self.oww.predict(chunk)[config.WAKE_MODEL]
                if score >= config.INTERRUPT_THRESHOLD:
                    sd.stop()
                    print("(interrupted)")
                    self.oww.reset()
                    return True
        finally:
            self._drain_queue()
        return False

    @staticmethod
    def _matches(text: str, phrases: list) -> bool:
        cleaned = "".join(c for c in text.lower() if c.isalpha() or c.isspace())
        return any(p in cleaned for p in phrases)

    def _is_stop_phrase(self, text: str) -> bool:
        return self._matches(text, config.STOP_PHRASES)

    def _is_close_phrase(self, text: str) -> bool:
        return self._matches(text, config.CLOSE_PHRASES)

    @staticmethod
    def _media_action(text: str) -> str | None:
        """Detect a terse media command (pause/skip/etc). Returns the action."""
        import re
        t = "".join(c for c in text.lower() if c.isalpha() or c.isspace()).strip()
        if len(t.split()) > 4:  # long sentence — not a terse media command
            return None
        mapping = [
            (("pause", "stop the music", "stop music", "stop the song"), "pause"),
            (("resume", "unpause", "continue", "carry on", "keep playing"), "play_pause"),
            (("next", "skip"), "next"),
            (("previous", "go back", "last song", "previous song"), "previous"),
        ]
        for phrases, action in mapping:
            if any(re.search(rf"\b{p}\b", t) for p in phrases):
                return action
        return None

    @staticmethod
    def _lookup_query(text: str) -> str | None:
        """If the user said 'look up X', return X — the thing to open tabs for."""
        import re
        m = re.search(r"\blook(?:\s*it)?\s*up\b\s+(.+)", text.strip(), re.IGNORECASE)
        if not m:
            return None
        q = m.group(1).strip().rstrip(".!?")
        q = re.sub(r"^(for|the|some|about)\s+", "", q, flags=re.IGNORECASE).strip()
        return q or None

    @staticmethod
    def _close_app_target(text: str) -> str | None:
        """If the user said 'close/quit/kill <known app>', return the app name."""
        import re

        import tools
        t = "".join(c for c in text.lower() if c.isalpha() or c.isspace())
        m = re.search(r"\b(?:close|quit|kill|exit)\s+(?:the\s+)?(.+)", t)
        if not m:
            return None
        rest = m.group(1).strip()
        for app in tools._APP_PROCESSES:
            if app in rest:
                return app
        return None

    @staticmethod
    def _open_app_target(text: str) -> str | None:
        """If the user said 'open/launch/start <known app>', return the app name."""
        import re

        import tools
        t = "".join(c for c in text.lower() if c.isalpha() or c.isspace())
        m = re.search(r"\b(?:open|launch|start|run)\s+(?:the\s+)?(.+)", t)
        if not m:
            return None
        rest = m.group(1).strip()
        for app in tools._APP_LAUNCH:
            if app in rest:
                return app
        return None

    @staticmethod
    def _play_query(text: str) -> str | None:
        """If the user wants to play something ('play X', 'put on X' anywhere in
        the sentence), return X — the thing to play. Otherwise None."""
        import re
        # match play/plays/played/playing or 'put on' anywhere, then capture
        # the rest as the query (handles transcription variants like "Played")
        m = re.search(r"\b(?:put on|play(?:s|ed|in|ing)?)\b(?:\s+(?:some|me|the|a))*\s+(.+)",
                      text.strip(), re.IGNORECASE)
        if not m:
            return None
        query = m.group(1).strip().rstrip(".!?")
        # trim a trailing filler word like "music"/"song"/"please"
        query = re.sub(r"\s+(music|songs?|please|for me)$", "", query,
                       flags=re.IGNORECASE).strip()
        # ignore media-control phrases ('play it again', 'play that')
        if not query or query.lower() in (
            "it", "it again", "that", "again", "this", "more"
        ):
            return None
        return query

    def conversation(self) -> None:
        """Active session: keep listening and answering until 'roger that'."""
        idle_rounds = 0
        while True:
            self.state["status"] = "recording"
            audio = self.record_command()
            self.oww.reset()

            if audio is None:
                idle_rounds += 1
                if idle_rounds >= config.CONVERSATION_MAX_IDLE_ROUNDS:
                    print("No speech for a while — going back to sleep.")
                    self.voice.say("Going back to sleep, sir.")
                    self._drain_queue()
                    return
                continue
            idle_rounds = 0

            path = os.path.join(
                config.RECORDINGS_DIR,
                f"command_{time.strftime('%Y%m%d_%H%M%S')}.wav",
            )
            save_wav(audio, path)
            self.state["status"] = "transcribing"
            text = self.transcriber.transcribe(audio)
            if not text:
                continue
            print(f'You said: "{text}"')

            if self._is_stop_phrase(text):
                self._log("you", text)
                self._log("jarvis", "Standing by.")
                print("Stop phrase — going back to sleep.")
                self.voice.say("Standing by.")
                beep(listening=False)
                self._drain_queue()
                return

            if self._is_close_phrase(text):
                import tools
                self._log("you", text)
                result = tools.close_tabs()
                reply = "Done." if result.startswith("Closed") else "Nothing to close."
                self._log("jarvis", reply)
                print(f"Close phrase — {result}")
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            lookup = self._lookup_query(text)
            if lookup:
                import tools
                self._log("you", text)
                self.state["status"] = "thinking"
                print(f"Look up — '{lookup}'")
                reply = tools.open_tabs(search_query=lookup)
                spoken = f"Looking up {lookup}."
                self._log("jarvis", spoken)
                self.state["status"] = "speaking"
                self.speak_interruptible(spoken)
                self._drain_queue()
                continue

            app_to_open = self._open_app_target(text)
            if app_to_open:
                import tools
                self._log("you", text)
                reply = tools.open_app(app_to_open)
                self._log("jarvis", reply)
                print(f"Open app — {reply}")
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            app_to_close = self._close_app_target(text)
            if app_to_close:
                import tools
                self._log("you", text)
                reply = tools.close_app(app_to_close)
                self._log("jarvis", reply)
                print(f"Close app — {reply}")
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            media = self._media_action(text)
            if media:
                import tools
                self._log("you", text)
                reply = tools.media_control(media)
                self._log("jarvis", reply)
                print(f"Media — {media}: {reply}")
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            play_query = self._play_query(text)
            if play_query:
                import re
                import tools
                self._log("you", text)
                service = "spotify" if "spotify" in text.lower() else "youtube"
                # strip "on spotify"/"on youtube" from the query itself
                play_query = re.sub(r"\s+on (spotify|youtube|you tube)\b", "",
                                    play_query, flags=re.IGNORECASE).strip()
                self.state["status"] = "thinking"
                print(f"Play phrase — '{play_query}' on {service}")
                reply = tools.play_music(play_query, service=service)
                self._log("jarvis", reply)
                self.state["status"] = "speaking"
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            if self._matches(text, config.BRIEFING_PHRASES):
                import tools
                self._log("you", text)
                self.state["status"] = "thinking"
                reply = tools.get_briefing(config.DEFAULT_LOCATION)
                self._log("jarvis", reply)
                print(f"Briefing — {reply}")
                self.state["status"] = "speaking"
                self.speak_interruptible(reply)
                self._drain_queue()
                continue

            self._log("you", text)
            self.state["status"] = "thinking"
            try:
                reply = self.brain.ask(text)
            except Exception as e:
                print(f"[brain error] {e}")
                reply = "Sorry, something went wrong with that."
            print(f'Jarvis: "{reply}"')
            self._log("jarvis", reply)
            self.state["status"] = "speaking"
            if self.speak_interruptible(reply):
                beep(listening=True)  # interrupted: go straight to listening

    def run(self) -> None:
        print(f"Listening for 'hey jarvis'... (Ctrl+C to quit)")
        self.state["status"] = "listening"
        with sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=config.CHUNK_SIZE,
            callback=self._callback,
        ):
            while True:
                chunk = self.audio_q.get()
                if self.state["muted"]:
                    self.state["status"] = "muted"
                    continue
                if self.state["status"] == "muted":
                    self.state["status"] = "listening"
                    self.oww.reset()
                score = self.oww.predict(chunk)[config.WAKE_MODEL]
                if score >= config.WAKE_THRESHOLD:
                    print(f"\nWake word detected (score {score:.2f}) — conversation started")
                    beep(listening=True)
                    self._drain_queue()  # drop audio buffered during the beep
                    self.oww.reset()
                    try:
                        self.conversation()
                    except Exception as e:
                        # one bad turn must never kill the listener
                        print(f"[conversation error] {e}")
                    self.state["status"] = "listening"
                    print("Listening for 'hey jarvis'...")


if __name__ == "__main__":
    try:
        Ears().run()
    except KeyboardInterrupt:
        print("\nJarvis ears shut down.")

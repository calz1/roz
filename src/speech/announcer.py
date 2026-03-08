"""Text-to-speech announcements using Piper TTS."""

import logging
import subprocess
import io
import wave
import threading
import queue
import time

logger = logging.getLogger("roz.speech.announcer")


class Announcer:
    """Handles text-to-speech announcements via Piper TTS."""

    def __init__(self, volume: float = 1.0, device: str = None, voice_model: str = "en_US-lessac-medium.onnx"):
        """Initialize announcer with TTS parameters.

        Args:
            volume: Volume level (0.0 to 1.0)
            device: ALSA device name (default: Auto-discover Jabra)
            voice_model: Piper voice model path (default: en_US-lessac-medium.onnx)
        """
        self.volume = volume
        self.device = device or self._find_jabra_device()
        self.voice_model = voice_model
        self.voice = None
        self.queue = queue.Queue()
        self.worker_thread = None
        self.should_stop = False
        self.last_audio_start_time = None  # When audio playback actually started
        self.last_frame_capture_time = None  # When the frame was captured

    def _find_jabra_device(self) -> str:
        """Attempt to find Jabra device via aplay -l. Fallback to default if not found."""
        try:
            output = subprocess.check_output(["aplay", "-l"], stderr=subprocess.STDOUT).decode()
            for line in output.splitlines():
                if "Jabra" in line and "card" in line:
                    # Example: card 4: USB [Jabra SPEAK 410 USB], device 0: USB Audio [USB Audio]
                    # We want to extract the card ID or use the name. 
                    # Using the CARD name is more stable than the index.
                    import re
                    match = re.search(r"card (\d+): (\S+) \[Jabra", line)
                    if match:
                        card_name = match.group(2)
                        return f"plughw:CARD={card_name},DEV=0"
            logger.warning("Jabra device not found in aplay -l, falling back to default")
        except Exception as e:
            logger.error(f"Error discovering Jabra device: {e}")
        
        return "default"

    def init_tts(self):
        """Initialize Piper TTS voice. Call this during main.py startup."""
        try:
            from piper import PiperVoice
            self.voice = PiperVoice.load(self.voice_model)
            logger.info("✓ Piper TTS initialized")
            # Start background worker thread
            self.should_stop = False
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
        except ImportError:
            logger.warning("Piper TTS not installed. Install with: uv add piper-tts")
            self.voice = None
        except Exception as e:
            logger.warning(f"Failed to initialize Piper: {e}")
            self.voice = None

    def announce(self, text: str, timeout: int = 10, frame_capture_time: float = None) -> bool:
        """Queue text for announcement via Piper TTS (non-blocking).

        Args:
            text: Text to speak
            timeout: Playback timeout in seconds
            frame_capture_time: Timestamp when the triggering frame was captured (for latency tracking)

        Returns:
            True if queued successfully, False otherwise
        """
        if not self.voice:
            logger.debug(f"TTS unavailable, would say: {text}")
            return False

        try:
            # Keep queue size limited to prevent stale announcements piling up
            # If queue gets too large, skip this announcement (it's probably old)
            queue_size = self.queue.qsize()
            if queue_size >= 2:
                logger.debug(f"TTS queue full ({queue_size} pending), skipping: {text[:50]}...")
                return False

            queue_time = time.time()
            queue_size_before = queue_size
            self.queue.put((text, timeout, frame_capture_time, queue_time))
            logger.debug(f"[TTS] Queued announcement (queue depth: {queue_size_before} -> {queue_size_before + 1}): {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to queue announcement: {e}")
            return False

    def _worker_loop(self):
        """Background worker thread for TTS synthesis and playback."""
        from piper import SynthesisConfig

        while not self.should_stop:
            try:
                text, timeout, frame_capture_time, queue_time = self.queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                synthesis_start = time.time()
                queue_wait = synthesis_start - queue_time if queue_time else 0

                # Log with frame capture context if available
                if frame_capture_time:
                    time_since_capture = synthesis_start - frame_capture_time
                    logger.info(f"[TTS] Starting synthesis (queued {queue_wait:.2f}s, {time_since_capture:.2f}s since capture): {text[:50]}...")
                else:
                    logger.info(f"[TTS] Starting synthesis: {text[:50]}...")

                syn_config = SynthesisConfig(volume=self.volume, length_scale=1.0)

                # Create WAV audio in memory
                audio_buffer = io.BytesIO()
                with wave.open(audio_buffer, 'wb') as wav_file:
                    self.voice.synthesize_wav(text, wav_file, syn_config=syn_config)
                audio_buffer.seek(0)

                synthesis_latency = time.time() - synthesis_start
                logger.info(f"[TTS] Synthesis complete in {synthesis_latency:.2f}s, starting playback...")

                # Play audio on USB speaker using aplay
                playback_start = time.time()
                self.last_audio_start_time = playback_start
                self.last_frame_capture_time = frame_capture_time

                try:
                    process = subprocess.Popen(
                        ["aplay", "-D", self.device],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    stdout, stderr = process.communicate(audio_buffer.read(), timeout=timeout)
                    if stderr:
                        logger.error(f"aplay stderr: {stderr.decode()}")
                    playback_latency = time.time() - playback_start
                    total_tts_time = synthesis_latency + playback_latency

                    # Log end-to-end latency if we have frame capture time
                    if frame_capture_time:
                        end_to_end = playback_start - frame_capture_time
                        total_with_playback = time.time() - frame_capture_time
                        logger.info(f"[TTS] ✓ Playback complete | Synth: {synthesis_latency:.2f}s | Play: {playback_latency:.2f}s | "
                                   f"Frame→Audio: {end_to_end:.2f}s | Frame→Done: {total_with_playback:.2f}s")
                    else:
                        logger.info(f"[TTS] ✓ Playback complete in {playback_latency:.2f}s")
                except FileNotFoundError:
                    logger.error("aplay not found. Install with: sudo apt-get install alsa-utils")
                except subprocess.TimeoutExpired:
                    process.kill()
                    logger.error(f"Audio playback timeout after {timeout}s")

            except Exception as e:
                logger.error(f"TTS announcement failed: {e}")

    def stop(self):
        """Stop the background worker thread."""
        if self.worker_thread:
            self.should_stop = True
            if self.worker_thread.is_alive():
                self.worker_thread.join(timeout=2)

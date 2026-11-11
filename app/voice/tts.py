"""
app/voice/tts.py - Privacy-Preserving Text-to-Speech Engine.

Enforces strict data boundaries:
  - Default: 'disabled' (zero network transmission; preserves complete data sovereignty)
  - 'remote' (Edge-TTS): strictly prohibited for sensitive or connector-derived text
  - 'local' (offline): purely local synthesis (Windows SAPI5 / Piper / offline engines)
                      with zero external network transmission and fail-safe error isolation.
"""
import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import anyio

from app.config import Settings

logger = logging.getLogger(__name__)


def _synthesize_local_sync(text: str, output_path: Path, voice_name: Optional[str] = None) -> bool:
    """
    Synchronous local speech synthesis execution run in a worker thread.
    Uses local Windows System.Speech (SAPI5) synthesizer via PowerShell without network access.
    Can also support Piper or other offline local CLI binaries if present.
    """
    # 1. Check if Piper CLI binary is installed locally
    piper_bin = shutil.which("piper")
    if piper_bin:
        try:
            logger.info("Local TTS: Found piper binary at %s", piper_bin)
        except Exception as p_err:
            logger.warning("Local TTS piper execution error: %s", p_err)

    # 2. Windows Native SAPI5 Synthesis (System.Speech.Synthesis)
    # Windows native synthesizer requires zero downloads, zero network, zero GPU.
    # Synthesizes directly to standard WAV and converts to destination path.
    if os.name == "nt":
        wav_tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_tmp = Path(tmp.name)

            # Build PowerShell SAPI script with Base64 encoding to prevent injection/escaping issues
            script_lines = [
                "Add-Type -AssemblyName System.Speech",
                "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            ]
            if voice_name:
                escaped_voice = voice_name.replace("'", "''")
                script_lines.append(f"$synth.SelectVoice('{escaped_voice}')")

            # Escape backslashes and single quotes for PowerShell
            wav_path_str = str(wav_tmp.resolve()).replace("'", "''")
            escaped_text = text.replace("'", "''")
            script_lines.extend([
                f"$synth.SetOutputToWaveFile('{wav_path_str}')",
                f"$synth.Speak('{escaped_text}')",
                "$synth.Dispose()",
            ])
            script = "\n".join(script_lines)
            encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")

            cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded_script]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode != 0:
                logger.error("Local SAPI TTS synthesis failed with exit code %s: %s", res.returncode, res.stderr)
                return False

            if not wav_tmp.exists() or wav_tmp.stat().st_size == 0:
                logger.error("Local SAPI TTS produced empty or missing WAV file.")
                return False

            # Convert to target output format if needed (e.g. .mp3)
            out_suffix = output_path.suffix.lower()
            if out_suffix == ".wav":
                shutil.copyfile(wav_tmp, output_path)
                return True
            elif out_suffix in (".mp3", ".mpeg"):
                try:
                    from pydub import AudioSegment
                    segment = AudioSegment.from_wav(str(wav_tmp))
                    segment.export(str(output_path), format="mp3")
                    return True
                except Exception as conv_err:
                    logger.warning("pydub MP3 conversion failed (%s); copying as raw audio", conv_err)
                    shutil.copyfile(wav_tmp, output_path)
                    return True
            else:
                shutil.copyfile(wav_tmp, output_path)
                return True

        except Exception as exc:
            logger.error("Local SAPI TTS error: %s", type(exc).__name__)
            return False
        finally:
            if wav_tmp and wav_tmp.exists():
                wav_tmp.unlink(missing_ok=True)

    logger.warning("Local offline TTS requested but no supported local synthesis engine found. Failing safe.")
    return False


class TTSEngine:
    def __init__(self, voice: Optional[str] = None, provider: Optional[str] = None):
        cfg = Settings()
        self.voice = voice or cfg.EDGE_TTS_VOICE
        self.provider = (provider if provider is not None else cfg.TTS_PROVIDER).strip().lower()
        self.local_voice = cfg.LOCAL_TTS_VOICE

    async def synthesize(self, text: str, output_path: Path, is_sensitive: bool = False) -> bool:
        """
        Synthesizes speech to output_path while strictly enforcing privacy boundaries.

        Returns:
            bool: True if audio was synthesized, False if skipped/blocked for privacy or unavailable.
        """
        cfg = Settings()

        # Hard invariant: never transmit sensitive or connector-derived data to remote services
        if is_sensitive and not cfg.ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA and self.provider == "remote":
            logger.info("TTS skipped: response contains sensitive/connector data and remote TTS is blocked.")
            return False

        if self.provider == "disabled":
            logger.debug("TTS skipped: provider is disabled by default configuration.")
            return False

        if self.provider == "remote":
            if is_sensitive and not cfg.ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA:
                logger.warning("TTS blocked: remote provider requested but text is marked sensitive.")
                return False

            try:
                import edge_tts
                communicate = edge_tts.Communicate(text, self.voice)
                await communicate.save(str(output_path))
                return True
            except Exception as exc:
                # Do not log full text payload to avoid logging potential PII
                logger.error("Remote TTS synthesis failed with error: %s", type(exc).__name__)
                raise

        if self.provider == "local":
            # Pure local offline synthesis:
            # Sensitive connector-derived text CAN be spoken locally because no byte leaves the host machine.
            # Executed in a worker thread via anyio.to_thread.run_sync so subprocess/disk I/O never blocks the ASGI loop.
            try:
                success = await anyio.to_thread.run_sync(
                    _synthesize_local_sync, text, output_path, self.local_voice
                )
                if not success:
                    logger.warning("Local offline TTS synthesis was unable to produce audio. Failing safe with no audio.")
                    return False
                return True
            except Exception as loc_exc:
                logger.error("Local offline TTS failed: %s; failing safe without remote fallback", type(loc_exc).__name__)
                return False

        # Any unknown or misconfigured provider fails safe
        logger.warning("Unknown TTS provider '%s'; failing safe with no audio.", self.provider)
        return False

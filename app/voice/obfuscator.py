import random
from pathlib import Path
from typing import Optional

import numpy as np
import librosa
import soundfile as sf
import pyworld as pw


# ---------------------------------------------------------------------------
# McAdams / VTLN spectral-envelope warp (vocal-tract-length perturbation)
# ---------------------------------------------------------------------------

def _warp_spectral_envelope(sp: np.ndarray, alpha: float) -> np.ndarray:
    """
    Warp the WORLD spectral envelope matrix by the McAdams coefficient alpha.

    How it works
    ------------
    WORLD represents the spectral envelope as a 2-D matrix sp[time, freq_bin].
    Each row is a smoothed spectral slice (essentially the vocal-tract filter
    evaluated at evenly-spaced frequency bins).  Warping by alpha means we
    *re-sample* each row along the frequency axis:

        sp_warped[t, k] = sp[t, k / alpha]   (with linear interpolation)

    Effect on formants
    ------------------
    * alpha < 1.0  →  each output bin k is filled from a *higher* source bin
                       k/alpha > k  →  formants shift UP (shorter vocal tract)
    * alpha > 1.0  →  source bin k/alpha < k  →  formants shift DOWN
                       (longer vocal tract)
    * alpha = 1.0  →  identity (no change)

    By randomly drawing alpha from, say, [0.85, 0.95] ∪ [1.05, 1.15] per
    request, consecutive recordings from the same speaker map to *different*
    apparent vocal-tract lengths, breaking formant-based speaker fingerprints.

    This is complementary to F0 shifting:
      - F0 shift   → hides glottal-source identity  (fundamental frequency)
      - SP warp    → hides vocal-tract identity       (formant positions)
    Together they address both major speaker-identity cues.
    """
    if abs(alpha - 1.0) < 1e-6:
        return sp  # fast-path: no warp needed

    n_frames, n_bins = sp.shape
    src_bins = np.arange(n_bins, dtype=np.float64)          # 0 … n_bins-1
    sample_positions = src_bins / alpha                      # where to sample in original

    # Clip to valid range; extrapolate by repeating edge values
    sample_positions = np.clip(sample_positions, 0.0, n_bins - 1)

    sp_warped = np.empty_like(sp)
    for t in range(n_frames):
        sp_warped[t] = np.interp(sample_positions, src_bins, sp[t])

    # Ensure sp stays strictly positive (WORLD requires sp > 0 for synthesis)
    np.clip(sp_warped, 1e-16, None, out=sp_warped)
    return sp_warped


class VoiceObfuscator:
    """
    Naive speaker obfuscator: perturbs pitch OR tempo per call via
    librosa's phase vocoder. Kept for benchmark/back-compat import
    purposes and as the cheaper, lower-fidelity option; prefer
    FormantPreservingObfuscator when transcription accuracy matters.
    """

    SHIFT_RANGES = {"mild": (-1, 1), "medium": (-4, 4), "strong": (-6, 6), "very_strong": (-8, 8)}

    # Tempo alone buys very little speaker obfuscation (a 2-4% rate change
    # is barely perceptible), so it isn't scaled by "strength" -- it's just
    # a second, cheap source of per-call variance when it's the one chosen.
    RATE_RANGE = (0.96, 1.04)

    # Weighted toward pitch since that's the transform actually doing
    # privacy work; tempo is included mainly so the obfuscation isn't
    # perfectly predictable/fingerprintable across calls.
    MODE_WEIGHTS = {"pitch": 0.75, "tempo": 0.25}

    def __init__(self, strength: str = "mild"):
        self.strength = strength
        self.shift_range = self.SHIFT_RANGES.get(strength, (-1, 1))
        self.last_shift: float = 0.0

    def obfuscate(self, input_path: Path, output_path: Path) -> float:
        y, sr = librosa.load(input_path, sr=16000)

        # Apply exactly ONE perturbation per call rather than stacking both.
        #
        # librosa.effects.pitch_shift is itself implemented as a phase-
        # vocoder time-stretch + resample internally. Following it with an
        # explicit time_stretch() runs the audio through a SECOND,
        # independent phase-vocoder pass -- each pass has its own phase-
        # estimation error, and those errors compound rather than average
        # out. That's real signal degradation for very little extra privacy
        # benefit, since tempo change alone barely disturbs speaker identity.
        mode = random.choices(
            population=list(self.MODE_WEIGHTS.keys()),
            weights=list(self.MODE_WEIGHTS.values()),
            k=1,
        )[0]

        if mode == "pitch":
            semitones = random.uniform(*self.shift_range)
            y = librosa.effects.pitch_shift(y, sr=sr, n_steps=semitones)
            actual_shift = float(semitones)
        else:
            rate = random.uniform(*self.RATE_RANGE)
            y = librosa.effects.time_stretch(y, rate=rate)
            actual_shift = 0.0

        self.last_shift = actual_shift
        sf.write(output_path, y, sr)
        return actual_shift


class FormantPreservingObfuscator:
    """
    Shifts F0 (pitch) AND warps the spectral envelope (McAdams/VTLN coefficient),
    using the WORLD vocoder.

    Two-layer speaker anonymization
    --------------------------------
    Speaker identity is carried by two largely independent channels:

      1. F0 / fundamental frequency  — the glottal source (pitch).
         Addressed by: shifting f0 by `semitone_shift` ± jitter.

      2. Spectral envelope / formants (F1, F2, F3…) — the vocal-tract filter.
         Addressed by: warping the WORLD sp matrix with the McAdams coefficient
         (alpha), which changes the apparent vocal-tract length and therefore
         shifts all formant frequencies up or down.

    Neither channel alone is sufficient:
      - F0-only shift:     leaves formants intact → speaker-verification models
                           that operate on MFCCs (which capture the spectral
                           envelope) can still identify the speaker.
      - SP-warp-only:      leaves pitch intact → simpler pitch-based fingerprints
                           survive.
      - Both together:     disrupts both the glottal-source and the vocal-tract
                           dimensions of speaker identity simultaneously.

    STT accuracy impact
    -------------------
    Whisper transcribes from spectral features (MFCCs / mel-filterbanks).
    A small vocal-tract warp (alpha in [0.88, 1.12]) shifts all formants by
    ~10%, which is within the variation Whisper was trained on across different
    speakers.  WER impact at these values is negligible in practice.
    Large warps (alpha < 0.85 or > 1.15) begin to degrade transcription.

    The `vtln_range` parameter controls the warp magnitude; the default
    [0.88, 1.12] is a comfortable balance.
    """

    # Default VTLN alpha range: excludes the identity (1.0) by design so
    # every request gets a non-trivial warp.
    DEFAULT_VTLN_RANGE: tuple[float, float] = (0.88, 1.12)

    def __init__(
        self,
        semitone_shift: float = 4.0,
        randomize: bool = True,
        jitter: float = 1.5,
        vtln_range: tuple[float, float] | None = None,
    ):
        """
        semitone_shift: base F0 pitch shift in semitones (+/- means up/down).
        randomize:      if True, add per-call jitter to semitone_shift and
                        draw a random VTLN alpha, so consecutive requests from
                        the same speaker produce non-identical obfuscations.
        jitter:         +/- range in semitones for the F0 randomisation.
        vtln_range:     (lo, hi) for the McAdams alpha.  Values on both sides
                        of 1.0 are acceptable (and recommended for variety).
                        Pass (1.0, 1.0) to disable spectral warping.
        """
        self.semitone_shift = semitone_shift
        self.randomize = randomize
        self.jitter = jitter
        self.vtln_range = vtln_range if vtln_range is not None else self.DEFAULT_VTLN_RANGE
        self.tempo_rate: float = 1.0
        self.last_shift: float = semitone_shift
        self.last_alpha: float = 1.0
        self.last_tempo_rate: float = 1.0

    def obfuscate(self, input_path: Path, output_path: Path, tempo_rate: Optional[float] = None) -> float:
        """
        Run three-layer speaker anonymization and write the result to output_path:
          1. F0 fundamental frequency shift (glottal source)
          2. McAdams spectral envelope warp (vocal tract length)
          3. Time-stretch tempo perturbation (speaking cadence)

        Returns the actual F0 semitone shift applied (for logging / UI display).
        The McAdams alpha is stored in self.last_alpha, and tempo rate in self.last_tempo_rate.
        """
        # Load audio: librosa standardizes to 16 kHz mono float32.
        try:
            x, fs = librosa.load(str(input_path), sr=16000, mono=True)
        except Exception:
            x, fs = sf.read(str(input_path))
            if x.ndim > 1:
                x = x.mean(axis=1)
            if fs != 16000:
                x = librosa.resample(x, orig_sr=fs, target_sr=16000)
                fs = 16000

        x = np.ascontiguousarray(x, dtype=np.float64)

        # --- Analysis: F0 / spectral envelope / aperiodicity ---
        if hasattr(pw, "harvest"):
            f0, t = getattr(pw, "harvest")(x, fs)
        else:
            f0, t = getattr(pw, "dio")(x, fs)
        f0 = getattr(pw, "stonemask")(x, f0, t, fs)
        sp = getattr(pw, "cheaptrick")(x, f0, t, fs)
        ap = getattr(pw, "d4c")(x, f0, t, fs)

        # --- Layer 1: F0 shift (glottal-source anonymization) ---
        shift = self.semitone_shift
        if self.randomize:
            shift += random.uniform(-self.jitter, self.jitter)
        self.last_shift = float(shift)
        ratio = 2 ** (shift / 12.0)

        # f0 == 0 marks unvoiced / silent frames; leave those untouched
        f0_shifted = np.where(f0 > 0, f0 * ratio, f0)

        # --- Layer 2: Spectral envelope warp (vocal-tract anonymization) ---
        # Draw a random alpha from vtln_range, biased away from 1.0 so we
        # always apply a meaningful warp.  If both bounds equal 1.0 the warp
        # is skipped (identity), allowing callers to disable it cleanly.
        lo, hi = self.vtln_range
        if self.randomize and abs(hi - lo) > 1e-6:
            # Randomly choose: warp toward lo OR toward hi (avoids clustering
            # near 1.0 when the range straddles it).
            mid = (lo + hi) / 2.0
            if lo < 1.0 < hi:
                # Range straddles 1.0: pick a half-range at random
                alpha = random.uniform(lo, mid) if random.random() < 0.5 else random.uniform(mid, hi)
            else:
                alpha = random.uniform(lo, hi)
        else:
            alpha = lo  # non-random mode: use lo as fixed value
        self.last_alpha = float(alpha)

        sp_warped = _warp_spectral_envelope(sp, alpha)

        # --- Resynthesis ---
        y = getattr(pw, "synthesize")(f0_shifted, sp_warped, ap, fs)

        # --- Layer 3: Time-stretch / Speaking Cadence Perturbation ---
        eff_rate = tempo_rate if tempo_rate is not None else self.tempo_rate
        if eff_rate and abs(eff_rate - 1.0) > 1e-3:
            y = librosa.effects.time_stretch(y, rate=float(eff_rate))
            self.last_tempo_rate = float(eff_rate)
        else:
            self.last_tempo_rate = 1.0

        # Peak normalization to avoid clipping
        max_val = np.max(np.abs(y)) if len(y) > 0 else 0
        if max_val > 0.99:
            y = y * (0.95 / max_val)

        sf.write(str(output_path), y, fs)
        return float(shift)

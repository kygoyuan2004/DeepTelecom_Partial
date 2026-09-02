#!/usr/bin/env python3
"""STFT and image utilities for the UAV micro-Doppler dataset."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def compute_stft(
    signal: np.ndarray,
    sampling_rate_hz: float,
    window_size: int,
    overlap: int,
    nfft: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    from scipy.signal import stft, windows

    nperseg = min(int(window_size), len(signal))
    noverlap = min(int(overlap), nperseg - 1)
    nfft = max(int(nfft), nperseg)
    f, t, z = stft(
        signal,
        fs=float(sampling_rate_hz),
        window=windows.hann(nperseg, sym=False),
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        return_onesided=False,
        boundary=None,
        padded=False,
    )
    f = np.fft.fftshift(f)
    z = np.fft.fftshift(z, axes=0)
    s_db = 20.0 * np.log10(np.abs(z) + 1e-12)
    s_db = s_db - float(np.max(s_db))
    return f.astype(np.float32), t.astype(np.float32), z.astype(np.complex64), s_db.astype(np.float32)


def stft_window_metrics(
    *,
    rotor_frequency_hz: float,
    micro_doppler_max_hz: float,
    sampling_rate_hz: float,
    stft_window_size: int,
) -> dict[str, float | bool]:
    t_rot = 1.0 / float(rotor_frequency_hz)
    t_win = int(stft_window_size) / float(sampling_rate_hz)
    ratio = t_win / t_rot
    strict = 2.0 * np.pi * float(rotor_frequency_hz) * abs(float(micro_doppler_max_hz)) * (t_win**2)
    return {
        "rotor_period_s": t_rot,
        "stft_window_duration_s": t_win,
        "stft_frequency_resolution_hz": 1.0 / t_win,
        "window_ratio_Twin_over_Trot": float(ratio),
        "window_strict_metric": float(strict),
        "window_check_pass": bool(ratio <= 0.25 and strict <= 1.0),
    }


def frequency_profile_metrics(f_axis: np.ndarray, s_db: np.ndarray, threshold_db: float = -35.0) -> dict[str, float]:
    profile = np.max(s_db, axis=1)
    peak_idx = int(np.argmax(profile))
    active = np.flatnonzero(profile >= threshold_db)
    if len(active) == 0:
        f_min = f_max = float(f_axis[peak_idx])
    else:
        f_min = float(f_axis[active[0]])
        f_max = float(f_axis[active[-1]])
    return {
        "stft_peak_observed_hz": float(f_axis[peak_idx]),
        "stft_support_min_observed_hz": f_min,
        "stft_support_max_observed_hz": f_max,
    }


def save_stft_image(
    s_db: np.ndarray,
    f_axis: np.ndarray,
    image_path: Path,
    *,
    f_min_hz: float,
    f_max_hz: float,
    dynamic_range_db: float,
    size: int = 512,
) -> None:
    import matplotlib
    from PIL import Image

    matplotlib.use("Agg")
    from matplotlib import colormaps

    mask = (f_axis >= float(f_min_hz)) & (f_axis <= float(f_max_hz))
    if not np.any(mask):
        selected = s_db
    else:
        selected = s_db[mask, :]
    norm = np.clip((selected + float(dynamic_range_db)) / float(dynamic_range_db), 0.0, 1.0)
    rgba = colormaps["turbo"](norm)
    rgb = (rgba[:, :, :3] * 255.0).astype(np.uint8)
    img = Image.fromarray(np.flipud(rgb), mode="RGB")
    img = img.resize((size, size), resample=Image.Resampling.BICUBIC)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(image_path)

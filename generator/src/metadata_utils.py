#!/usr/bin/env python3
"""Configuration and metadata helpers for the standalone UAV STFT dataset."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METADATA_FIELDS = [
    "sample_id",
    "class_id",
    "image_path",
    "tensor_path",
    "scene_name",
    "scene_channel_model",
    "scene_xml_path",
    "scene_tx_name",
    "scene_source",
    "scene_loaded",
    "scene_load_error",
    "carrier_frequency_hz",
    "sampling_rate_hz",
    "num_snapshots",
    "snapshot_duration_s",
    "stft_window_size",
    "stft_overlap",
    "stft_nfft",
    "stft_window_duration_s",
    "stft_frequency_resolution_hz",
    "rotor_frequency_hz",
    "rotor_period_s",
    "omega_rad_s",
    "omega_h_rad_s",
    "omega_theta_rad_s",
    "omega_theta_over_omega_h",
    "degree",
    "degree_rad",
    "body_speed_m_s",
    "body_velocity_x",
    "body_velocity_y",
    "body_velocity_z",
    "body_acceleration_x",
    "body_acceleration_y",
    "body_acceleration_z",
    "blade_radius_m",
    "num_uavs",
    "num_rotors",
    "num_blades_per_rotor",
    "points_per_blade",
    "num_scatterers",
    "doppler_body_theory_hz",
    "micro_doppler_max_theory_hz",
    "doppler_support_min_theory_hz",
    "doppler_support_max_theory_hz",
    "stft_support_min_observed_hz",
    "stft_support_max_observed_hz",
    "stft_peak_observed_hz",
    "window_ratio_Twin_over_Trot",
    "window_strict_metric",
    "window_check_pass",
    "random_seed",
    "noise_snr_db",
    "created_time",
    "initial_body_position_x",
    "initial_body_position_y",
    "initial_body_position_z",
    "initial_rotor_phase_rad",
    "bs_position_x",
    "bs_position_y",
    "bs_position_z",
]


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if any(ch in text.lower() for ch in [".", "e"]):
            return float(text)
        return int(text)
    except ValueError:
        return text.strip("'\"")


def load_simple_yaml(path: Path) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        cfg[key.strip()] = parse_scalar(value)
    return cfg


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_metadata_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_manifest_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_metadata_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    counts = Counter(str(row["class_id"]) for row in rows)
    lines = [
        "# UAV STFT Dataset Metadata Summary",
        "",
        f"- Total samples: `{len(rows)}`",
        "- Note: `omiga` in older notes is a misspelling; this dataset uses `omega` consistently.",
        "",
        "## Class Counts",
        "",
        "| class_id | samples | degree | body speed [m/s] |",
        "| --- | ---: | ---: | ---: |",
    ]
    for class_id in sorted(counts):
        first = next(row for row in rows if row["class_id"] == class_id)
        lines.append(f"| `{class_id}` | {counts[class_id]} | {first['degree']} | {first['body_speed_m_s']} |")
    lines.extend(
        [
            "",
            "## Required Field Snapshot",
            "",
            "| field | example |",
            "| --- | --- |",
        ]
    )
    if rows:
        first = rows[0]
        for field in METADATA_FIELDS[:48]:
            lines.append(f"| `{field}` | `{first.get(field, '')}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

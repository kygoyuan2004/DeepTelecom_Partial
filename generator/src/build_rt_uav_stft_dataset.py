#!/usr/bin/env python3
"""Build a UAV micro-Doppler dataset with Sionna RT PathSolver.

This is the portable DeepTelecom UAV generator. It calls the actual
Sionna RT PathSolver for every configured RT snapshot. The UAV body/blade
scatterers are represented as passive Receiver probes, their positions are
updated, and the one-way BS-to-probe CIR is coherently summed into a monostatic
return.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_SCRIPTS = PROJECT_ROOT / "src"
if str(DATASET_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DATASET_SCRIPTS))

from metadata_utils import METADATA_FIELDS  # noqa: E402
from motion_utils import (  # noqa: E402
    CLASS_SPECS,
    ClassSpec,
    SPEED_OF_LIGHT,
    build_default_weights,
    monostatic_doppler_theory,
    omega_theta_ratio,
    rotation_y,
    scatterer_count,
    scatterer_trajectories,
)
from stft_utils import (  # noqa: E402
    compute_stft,
    frequency_profile_metrics,
    save_stft_image,
    stft_window_metrics,
)


RT_CLASS_SPECS: dict[str, ClassSpec] = {
    "level_v0": CLASS_SPECS["level_v0"],
    "pitch30_v10": CLASS_SPECS["pitch30_v10"],
    "pitch45_v10": CLASS_SPECS["pitch45_v10"],
    "single_blade_v0": ClassSpec("single_blade_v0", 0.0, 0.0),
}

CLASS_ALIASES: dict[str, list[str]] = {
    "single_blade": ["single_blade_v0"],
    "single-blade": ["single_blade_v0"],
    "pitch30_v10.45": ["pitch30_v10", "pitch45_v10"],
}


RT_FIELDNAMES = list(dict.fromkeys(METADATA_FIELDS + [
    "sample_elapsed_s",
    "scene_channel_model",
    "scene_source",
    "scene_merge_shapes",
    "body_trajectory_model",
    "etoile_trajectory_speed_mode",
    "etoile_trajectory_start_fraction",
    "etoile_trajectory_start_distance_m",
    "etoile_trajectory_speed_m_s",
    "etoile_trajectory_path_length_m",
    "etoile_trajectory_control_points_json",
    "rt_solver",
    "rt_max_depth",
    "rt_los",
    "rt_specular_reflection",
    "rt_diffuse_reflection",
    "rt_diffraction",
    "rt_refraction",
    "rt_snapshot_stride",
    "rt_snapshots_solved",
    "rt_elapsed_s",
    "rt_total_valid_paths",
    "rt_min_valid_paths_per_solved_snapshot",
    "rt_max_valid_paths_per_solved_snapshot",
    "rt_cir_sampling_frequency_hz",
]))


TIMING_FIELDNAMES = [
    "sample_id",
    "class_id",
    "num_snapshots",
    "rt_snapshot_stride",
    "rt_snapshots_solved",
    "rt_elapsed_s",
    "sample_elapsed_s",
    "rt_elapsed_per_solved_snapshot_s",
    "created_time",
]


def write_rt_metadata_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.write.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def write_rt_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.write.tmp")
    with temporary.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def write_timing_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.write.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TIMING_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            timing = dict(row)
            solved = max(1, int(float(row.get("rt_snapshots_solved", 1))))
            timing["rt_elapsed_per_solved_snapshot_s"] = float(row.get("rt_elapsed_s", 0.0)) / solved
            writer.writerow(timing)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    lower = raw.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        if any(ch in raw for ch in [".", "e", "E"]):
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def read_simple_yaml(path: Path) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        cfg[key.strip()] = parse_scalar(value)
    return cfg


def resolve_config_paths(cfg: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Resolve bundled asset paths relative to the YAML file, not the shell CWD."""

    resolved = dict(cfg)
    for key in ("scene_xml_path", "calibrated_materials_json"):
        raw = str(resolved.get(key, "") or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.resolve().parent / candidate
        resolved[key] = str(candidate.resolve())
    return resolved


def expand_class_args(classes: list[str]) -> list[str]:
    expanded: list[str] = []
    for raw in classes:
        for token in str(raw).replace(",", " ").split():
            mapped = CLASS_ALIASES.get(token, [token])
            for class_id in mapped:
                if class_id not in expanded:
                    expanded.append(class_id)
    return expanded


def ensure_dirs(root: Path) -> None:
    for rel in ["database", "reports", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    for class_id in RT_CLASS_SPECS:
        (root / "images" / class_id).mkdir(parents=True, exist_ok=True)
        (root / "tensors" / class_id).mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_awgn(signal: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    power = float(np.mean(np.abs(signal) ** 2))
    if power <= 0.0:
        return signal.copy()
    noise_power = power / (10.0 ** (float(snr_db) / 10.0))
    noise = math.sqrt(noise_power / 2.0) * (
        rng.standard_normal(signal.shape) + 1j * rng.standard_normal(signal.shape)
    )
    return signal + noise


def load_scene_with_options(scene_ref: Any, *, merge_shapes: bool):
    from sionna.rt import load_scene

    try:
        return load_scene(scene_ref, merge_shapes=bool(merge_shapes))
    except TypeError:
        return load_scene(scene_ref)


def apply_calibrated_materials(scene: Any, material_json: str | Path) -> Path:
    """Apply a calibration export after setting the scene frequency."""

    path = Path(material_json).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    scene_frequency = float(scene.frequency[0])
    expected_frequency = float(payload.get("frequency_hz", scene_frequency))
    if not math.isclose(
        expected_frequency,
        scene_frequency,
        rel_tol=1e-9,
        abs_tol=1.0,
    ):
        raise ValueError(
            f"Calibration frequency {expected_frequency} Hz does not match "
            f"scene frequency {scene_frequency} Hz"
        )
    materials = payload.get("materials", {})
    if not isinstance(materials, dict) or not materials:
        raise ValueError(f"No materials found in calibration export: {path}")
    unknown = sorted(set(materials) - set(scene.radio_materials))
    if unknown:
        raise ValueError(f"Calibration export contains unknown scene materials: {unknown}")
    for name, values in materials.items():
        material = scene.radio_materials[name]
        material.relative_permittivity = float(values["relative_permittivity"])
        material.conductivity = float(values["conductivity_s_per_m"])
        if "scattering_coefficient" in values:
            material.scattering_coefficient = float(values["scattering_coefficient"])
    return path


def load_rt_scene(cfg: dict[str, Any]):
    import sionna
    from sionna.rt import PlanarArray

    scene_xml = str(cfg.get("scene_xml_path", "") or "").strip()
    merge_shapes = bool(cfg.get("scene_merge_shapes", False))
    if scene_xml:
        scene = load_scene_with_options(scene_xml, merge_shapes=merge_shapes)
        # Publish a stable logical reference instead of a machine-local path.
        scene_source = f"scene_xml:{Path(scene_xml).name}"
    else:
        scene_name = str(cfg.get("scene_name", "floor_wall"))
        if not hasattr(sionna.rt.scene, scene_name):
            raise ValueError(f"Sionna RT does not provide a built-in scene named {scene_name!r}")
        scene_obj = getattr(sionna.rt.scene, scene_name)
        scene = load_scene_with_options(scene_obj, merge_shapes=merge_shapes)
        scene_source = f"sionna.rt.scene.{scene_name}"

    scene.frequency = float(cfg["carrier_frequency_hz"])
    calibrated_materials = str(cfg.get("calibrated_materials_json", "") or "").strip()
    if calibrated_materials:
        applied_path = apply_calibrated_materials(scene, calibrated_materials)
        scene_source = f"{scene_source}; calibrated_materials={applied_path.name}"
    scene.tx_array = PlanarArray(
        num_rows=1,
        num_cols=1,
        vertical_spacing=0.5,
        horizontal_spacing=0.5,
        pattern="iso",
        polarization="V",
    )
    scene.rx_array = PlanarArray(
        num_rows=1,
        num_cols=1,
        vertical_spacing=0.5,
        horizontal_spacing=0.5,
        pattern="iso",
        polarization="V",
    )
    return scene, scene_source


ETOILE_DEFAULT_CONTROL_POINTS = np.asarray(
    [
        [146.0, -52.0, 70.0],
        [154.0, -18.0, 70.0],
        [178.0, 14.0, 70.0],
        [204.0, -8.0, 70.0],
    ],
    dtype=np.float64,
)


def cfg_float(cfg: dict[str, Any], key: str, default: float) -> float:
    return float(cfg.get(key, default))


def etoile_control_points(cfg: dict[str, Any]) -> np.ndarray:
    raw_json = str(cfg.get("etoile_control_points_json", "") or "").strip()
    if raw_json:
        points = np.asarray(json.loads(raw_json), dtype=np.float64)
        if points.shape != (4, 3):
            raise ValueError(f"etoile_control_points_json must have shape [4,3], got {points.shape}")
        return points

    points = ETOILE_DEFAULT_CONTROL_POINTS.copy()
    for idx in range(4):
        for axis, axis_name in enumerate(["x", "y", "z"]):
            key = f"etoile_control{idx}_{axis_name}_m"
            if key in cfg:
                points[idx, axis] = float(cfg[key])
    return points


def cubic_bezier(control: np.ndarray, t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=np.float64)[:, None]
    return (
        ((1.0 - t) ** 3) * control[0]
        + 3.0 * ((1.0 - t) ** 2) * t * control[1]
        + 3.0 * (1.0 - t) * (t**2) * control[2]
        + (t**3) * control[3]
    )


def bezier_arc_table(control: np.ndarray, n_dense: int = 4096) -> tuple[np.ndarray, np.ndarray, float]:
    dense_t = np.linspace(0.0, 1.0, int(n_dense), dtype=np.float64)
    dense_pts = cubic_bezier(control, dense_t)
    seg_len = np.linalg.norm(np.diff(dense_pts, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_len)])
    return dense_t, cumulative, float(cumulative[-1])


def sample_bezier_by_distance(
    control: np.ndarray,
    distances_m: np.ndarray,
    *,
    dense_t: np.ndarray,
    cumulative_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    total = float(cumulative_m[-1])
    distances = np.clip(np.asarray(distances_m, dtype=np.float64), 0.0, total)
    sample_t = np.interp(distances, cumulative_m, dense_t)
    positions = cubic_bezier(control, sample_t)

    eps = 1e-4
    t0 = np.clip(sample_t - eps, 0.0, 1.0)
    t1 = np.clip(sample_t + eps, 0.0, 1.0)
    p0 = cubic_bezier(control, t0)
    p1 = cubic_bezier(control, t1)
    tangent = p1 - p0
    norm = np.linalg.norm(tangent, axis=1, keepdims=True)
    tangent_unit = tangent / np.maximum(norm, 1e-12)
    return positions, tangent_unit


def build_body_path(
    *,
    cfg: dict[str, Any],
    spec: ClassSpec,
    rng: np.random.Generator,
    num_snapshots: int,
    sampling_rate_hz: float,
    linear_position0: np.ndarray,
    linear_velocity0: np.ndarray,
) -> dict[str, Any]:
    model = str(cfg.get("body_trajectory_model", "linear") or "linear")
    t = np.arange(int(num_snapshots), dtype=np.float64) / float(sampling_rate_hz)

    if model == "linear":
        positions = linear_position0[None, :] + t[:, None] * linear_velocity0[None, :]
        return {
            "model": "linear",
            "positions": positions.astype(np.float32),
            "velocities": np.broadcast_to(linear_velocity0[None, :], positions.shape).astype(np.float32),
            "speed_mode": "class_speed",
            "start_fraction": "",
            "start_distance_m": "",
            "speed_m_s": float(np.linalg.norm(linear_velocity0)),
            "path_length_m": "",
            "control_points": np.empty((0, 3), dtype=np.float32),
            "distances_m": np.zeros(len(t), dtype=np.float32),
        }
    if model != "etoile_bezier":
        raise ValueError(
            "Unsupported body_trajectory_model "
            f"{model!r}; choose 'linear' or 'etoile_bezier'. "
            "Waypoint trajectories are not implemented."
        )

    control = etoile_control_points(cfg)
    dense_t, cumulative_m, path_length_m = bezier_arc_table(control)
    speed_mode = str(cfg.get("etoile_trajectory_speed_mode", "class_speed") or "class_speed")
    if speed_mode == "handoff_nominal":
        speed_m_s = cfg_float(cfg, "etoile_trajectory_nominal_speed_m_s", 18.145619428797083)
    else:
        speed_m_s = float(spec.body_speed_m_s)

    span_m = max(0.0, speed_m_s * float(t[-1] if len(t) else 0.0))
    min_frac = cfg_float(cfg, "etoile_start_fraction_min", 0.0)
    max_frac = cfg_float(cfg, "etoile_start_fraction_max", 0.98)
    min_distance = np.clip(min_frac, 0.0, 1.0) * path_length_m
    max_distance = min(np.clip(max_frac, 0.0, 1.0) * path_length_m, max(0.0, path_length_m - span_m))
    if max_distance < min_distance:
        max_distance = min_distance
    if max_distance > min_distance:
        start_distance_m = float(rng.uniform(min_distance, max_distance))
    else:
        start_distance_m = float(min_distance)

    distances_m = start_distance_m + speed_m_s * t
    positions, tangent_unit = sample_bezier_by_distance(
        control,
        distances_m,
        dense_t=dense_t,
        cumulative_m=cumulative_m,
    )
    velocities = tangent_unit * speed_m_s
    if speed_m_s == 0.0:
        velocities[:] = 0.0

    jitter = cfg_float(cfg, "position_jitter_m", 0.0)
    if jitter:
        positions = positions + rng.uniform(-jitter, jitter, size=3)[None, :]

    return {
        "model": model,
        "positions": positions.astype(np.float32),
        "velocities": velocities.astype(np.float32),
        "speed_mode": speed_mode,
        "start_fraction": float(start_distance_m / path_length_m) if path_length_m else 0.0,
        "start_distance_m": start_distance_m,
        "speed_m_s": speed_m_s,
        "path_length_m": path_length_m,
        "control_points": control.astype(np.float32),
        "distances_m": distances_m.astype(np.float32),
    }


def attach_body_path(traj: dict[str, Any], body_path: dict[str, Any]) -> dict[str, Any]:
    positions = np.asarray(body_path["positions"], dtype=np.float32)
    velocities = np.asarray(body_path["velocities"], dtype=np.float32)
    out = dict(traj)
    out["positions"] = (np.asarray(traj["positions"], dtype=np.float32) + positions[:, None, :]).astype(np.float32)
    out["velocities"] = (np.asarray(traj["velocities"], dtype=np.float32) + velocities[:, None, :]).astype(np.float32)
    out["rotor_centers"] = (np.asarray(traj["rotor_centers"], dtype=np.float32) + positions[:, None, :]).astype(np.float32)
    return out


def setup_scene(cfg: dict[str, Any], initial_positions: np.ndarray, labels: list[str]):
    from sionna.rt import Receiver, Transmitter

    scene, scene_source = load_rt_scene(cfg)
    bs = [
        float(cfg["bs_position_x"]),
        float(cfg["bs_position_y"]),
        float(cfg["bs_position_z"]),
    ]
    scene.add(
        Transmitter(
            name=str(cfg.get("scene_tx_name", "bs_radar")),
            position=bs,
            orientation=[0.0, 0.0, 0.0],
            power_dbm=0.0,
        )
    )

    probe_names = []
    for idx, (label, pos) in enumerate(zip(labels, initial_positions)):
        name = f"probe_{idx:03d}_{label}".replace(".", "p")
        scene.add(
            Receiver(
                name=name,
                position=np.asarray(pos, dtype=np.float64).tolist(),
                orientation=[0.0, 0.0, 0.0],
            )
        )
        probe_names.append(name)
    return scene, scene_source, probe_names


def update_probe_positions(scene: Any, probe_names: list[str], positions: np.ndarray) -> None:
    for name, pos in zip(probe_names, positions):
        scene.get(name).position = np.asarray(pos, dtype=np.float64).tolist()


def run_solver(scene: Any, solver: Any, cfg: dict[str, Any]) -> np.ndarray:
    paths = solver(
        scene,
        max_depth=int(cfg.get("rt_max_depth", 2)),
        los=bool(cfg.get("rt_los", True)),
        specular_reflection=bool(cfg.get("rt_specular_reflection", True)),
        diffuse_reflection=bool(cfg.get("rt_diffuse_reflection", False)),
        diffraction=bool(cfg.get("rt_diffraction", False)),
        edge_diffraction=bool(cfg.get("rt_edge_diffraction", False)),
        refraction=bool(cfg.get("rt_refraction", False)),
        synthetic_array=bool(cfg.get("rt_synthetic_array", False)),
    )
    a, _ = paths.cir(
        sampling_frequency=float(cfg.get("rt_cir_sampling_frequency_hz", 122.88e6)),
        normalize_delays=False,
        out_type="numpy",
    )
    return np.asarray(a, dtype=np.complex128)


def one_way_channels_by_rx(a: np.ndarray, n_receivers: int) -> tuple[np.ndarray, np.ndarray]:
    if a.ndim != 6:
        raise ValueError(f"Expected 6-D CIR coefficient tensor, got shape {a.shape}")
    if a.shape[0] < n_receivers:
        raise ValueError(f"Expected at least {n_receivers} receivers, got {a.shape[0]}")
    coeff = a[:n_receivers, 0, 0, 0, :, 0]
    valid = np.abs(coeff) > 0.0
    return np.sum(coeff, axis=-1), np.sum(valid, axis=-1).astype(np.int32)


def interp_complex(solved_indices: np.ndarray, solved_values: np.ndarray, n: int) -> np.ndarray:
    full_idx = np.arange(n, dtype=np.float64)
    out = np.empty((n, solved_values.shape[1]), dtype=np.complex128)
    for k in range(solved_values.shape[1]):
        real = np.interp(full_idx, solved_indices.astype(np.float64), solved_values[:, k].real)
        imag = np.interp(full_idx, solved_indices.astype(np.float64), solved_values[:, k].imag)
        out[:, k] = real + 1j * imag
    return out


def single_blade_tip_trajectory(
    *,
    num_snapshots: int,
    sampling_rate_hz: float,
    rotor_center: np.ndarray,
    body_velocity0: np.ndarray,
    degree_rad: float,
    rotor_frequency_hz: float,
    blade_radius_m: float,
    initial_phase: float,
) -> dict[str, Any]:
    """Generate one rotating blade-tip scatterer for the clean v=0 RT class."""

    t = np.arange(int(num_snapshots), dtype=np.float64) / float(sampling_rate_hz)
    center0 = np.asarray(rotor_center, dtype=np.float64)
    body_velocity0 = np.asarray(body_velocity0, dtype=np.float64)
    centers = center0[None, :] + t[:, None] * body_velocity0[None, :]

    omega = 2.0 * np.pi * float(rotor_frequency_hz)
    phi = omega * t + float(initial_phase)
    rho = float(blade_radius_m)
    r_body_to_world = rotation_y(degree_rad)

    rel_local = np.stack([rho * np.cos(phi), rho * np.sin(phi), np.zeros_like(t)], axis=1)
    vel_local = np.stack([-omega * rho * np.sin(phi), omega * rho * np.cos(phi), np.zeros_like(t)], axis=1)
    rel_world = rel_local @ r_body_to_world.T
    vel_world = vel_local @ r_body_to_world.T

    positions = (centers[:, None, :] + rel_world[:, None, :]).astype(np.float32)
    velocities = (body_velocity0[None, None, :] + vel_world[:, None, :]).astype(np.float32)
    rotor_centers = centers[:, None, :].astype(np.float32)

    return {
        "t": t.astype(np.float32),
        "positions": positions,
        "velocities": velocities,
        "rotor_centers": rotor_centers,
        "labels": ["single_blade_tip"],
        "radii": np.asarray([rho], dtype=np.float32),
        "scatterer_type_codes": np.asarray([1], dtype=np.int32),
        "rotor_ids": np.asarray([0], dtype=np.int32),
    }


def generate_case(
    *,
    cfg: dict[str, Any],
    root: Path,
    class_id: str,
    sample_index: int,
    snapshot_override: int | None = None,
) -> dict[str, Any]:
    sample_start = time.perf_counter()
    spec = RT_CLASS_SPECS[class_id]
    seed = int(cfg["random_seed"]) + sample_index + 100000 * list(RT_CLASS_SPECS).index(class_id)
    rng = np.random.default_rng(seed)

    num_snapshots = int(snapshot_override or cfg["num_snapshots"])
    fs = float(cfg["sampling_rate_hz"])
    rotor_frequency = float(cfg["rotor_frequency_hz"]) * rng.uniform(
        1.0 - float(cfg.get("rotor_frequency_jitter_fraction", 0.0)),
        1.0 + float(cfg.get("rotor_frequency_jitter_fraction", 0.0)),
    )
    blade_radius = float(cfg["blade_radius_m"]) * rng.uniform(
        1.0 - float(cfg.get("blade_radius_jitter_fraction", 0.0)),
        1.0 + float(cfg.get("blade_radius_jitter_fraction", 0.0)),
    )
    noise_snr = rng.uniform(float(cfg["noise_snr_min_db"]), float(cfg["noise_snr_max_db"]))
    position_jitter = float(cfg.get("position_jitter_m", 0.0))
    body_position0 = np.asarray(
        [
            float(cfg["body_position_x"]),
            float(cfg["body_position_y"]),
            float(cfg["body_position_z"]),
        ],
        dtype=np.float64,
    )
    if position_jitter:
        body_position0 += rng.uniform(-position_jitter, position_jitter, size=3)
    body_velocity0 = np.asarray([float(spec.body_speed_m_s), 0.0, 0.0], dtype=np.float64)
    body_acceleration = np.zeros(3, dtype=np.float64)
    degree_rad = math.radians(float(spec.degree))
    body_path = build_body_path(
        cfg=cfg,
        spec=spec,
        rng=rng,
        num_snapshots=num_snapshots,
        sampling_rate_hz=fs,
        linear_position0=body_position0,
        linear_velocity0=body_velocity0,
    )
    num_uavs = int(cfg["num_uavs"])
    if num_uavs != 1:
        raise ValueError(
            "This generator currently models one UAV per sample. "
            f"Received num_uavs={num_uavs}; refusing to save ambiguous per-UAV trajectories."
        )
    uav_positions_m = np.asarray(body_path["positions"], dtype=np.float32)[:, None, :]
    uav_velocities_m_s = np.asarray(body_path["velocities"], dtype=np.float32)[:, None, :]
    uav_speeds_m_s = np.linalg.norm(uav_velocities_m_s, axis=-1).astype(np.float32)
    uav_ids = np.asarray(["uav_000"])
    body_position0 = np.asarray(body_path["positions"][0], dtype=np.float64)
    body_velocity0 = np.asarray(body_path["velocities"][0], dtype=np.float64)
    if class_id == "single_blade_v0":
        num_rotors = 1
        num_blades = 1
        points_per_blade = 1
    else:
        num_rotors = int(cfg["num_rotors"])
        num_blades = int(cfg["num_blades_per_rotor"])
        points_per_blade = int(cfg["points_per_blade"])
    initial_phase = rng.uniform(0.0, 2.0 * np.pi)
    blade_phase_offsets = rng.uniform(-0.08, 0.08, size=(num_rotors, num_blades))

    if class_id == "single_blade_v0":
        rotor_center = body_position0
        rotor_velocity = body_velocity0
        if body_path["model"] == "etoile_bezier":
            rotor_center = np.zeros(3, dtype=np.float64)
            rotor_velocity = np.zeros(3, dtype=np.float64)
        traj = single_blade_tip_trajectory(
            num_snapshots=num_snapshots,
            sampling_rate_hz=fs,
            rotor_center=rotor_center,
            body_velocity0=rotor_velocity,
            degree_rad=degree_rad,
            rotor_frequency_hz=rotor_frequency,
            blade_radius_m=blade_radius,
            initial_phase=initial_phase,
        )
        if body_path["model"] == "etoile_bezier":
            traj = attach_body_path(traj, body_path)
        weights = np.asarray([1.0], dtype=np.float64)
        n_scatterers = 1
    else:
        traj_position0 = body_position0
        traj_velocity0 = body_velocity0
        if body_path["model"] == "etoile_bezier":
            traj_position0 = np.zeros(3, dtype=np.float64)
            traj_velocity0 = np.zeros(3, dtype=np.float64)
        traj = scatterer_trajectories(
            num_snapshots=num_snapshots,
            sampling_rate_hz=fs,
            body_position0=traj_position0,
            body_velocity0=traj_velocity0,
            body_acceleration=body_acceleration,
            degree_rad=degree_rad,
            rotor_frequency_hz=rotor_frequency,
            blade_radius_m=blade_radius,
            rotor_arm_length_m=float(cfg["rotor_arm_length_m"]),
            num_rotors=num_rotors,
            num_blades_per_rotor=num_blades,
            points_per_blade=points_per_blade,
            initial_rotor_phase=initial_phase,
            blade_phase_offsets=blade_phase_offsets,
        )
        if body_path["model"] == "etoile_bezier":
            traj = attach_body_path(traj, body_path)
        weights = build_default_weights(
            num_rotors,
            num_blades,
            points_per_blade,
            rng,
            float(cfg.get("scatterer_weight_jitter_fraction", 0.0)),
        )
        n_scatterers = scatterer_count(num_rotors, num_blades, points_per_blade)

    scene, scene_source, probe_names = setup_scene(cfg, traj["positions"][0], traj["labels"])
    from sionna.rt import PathSolver

    solver = PathSolver()
    stride = max(1, int(cfg.get("rt_snapshot_stride", 1)))
    solved_indices = np.arange(0, num_snapshots, stride, dtype=np.int32)
    if solved_indices[-1] != num_snapshots - 1:
        solved_indices = np.append(solved_indices, num_snapshots - 1)

    h_solved = np.zeros((len(solved_indices), n_scatterers), dtype=np.complex128)
    path_counts_solved = np.zeros((len(solved_indices), n_scatterers), dtype=np.int32)
    start = time.perf_counter()
    for j, snap_idx in enumerate(solved_indices):
        update_probe_positions(scene, probe_names, traj["positions"][int(snap_idx)])
        a = run_solver(scene, solver, cfg)
        h, counts = one_way_channels_by_rx(a, n_scatterers)
        h_solved[j] = h
        path_counts_solved[j] = counts
        if (j + 1) % max(1, len(solved_indices) // 4) == 0:
            print(f"  {class_id}_{sample_index:04d}: RT {j + 1}/{len(solved_indices)} solved snapshots", flush=True)
    rt_elapsed = time.perf_counter() - start

    if len(solved_indices) == num_snapshots:
        csi_one_way = h_solved
        path_counts = path_counts_solved
    else:
        csi_one_way = interp_complex(solved_indices, h_solved, num_snapshots)
        path_counts = np.rint(
            np.vstack([
                np.interp(np.arange(num_snapshots), solved_indices, path_counts_solved[:, k])
                for k in range(n_scatterers)
            ]).T
        ).astype(np.int32)

    return_per_scatterer = weights[None, :] * csi_one_way * csi_one_way
    signal_clean = np.sum(return_per_scatterer, axis=1)
    signal_noisy = add_awgn(signal_clean, noise_snr, rng)
    f_axis, t_axis, s_complex, s_db = compute_stft(
        signal_noisy,
        fs,
        int(cfg["stft_window_size"]),
        int(cfg["stft_overlap"]),
        int(cfg["stft_nfft"]),
    )

    bs_position = np.asarray([float(cfg["bs_position_x"]), float(cfg["bs_position_y"]), float(cfg["bs_position_z"])])
    freqs = monostatic_doppler_theory(
        traj["positions"],
        traj["velocities"],
        bs_position,
        float(cfg["carrier_frequency_hz"]),
    )
    body_freq = float(np.median(freqs[:, 0]))
    f_min_theory = float(np.min(freqs))
    f_max_theory = float(np.max(freqs))
    micro_max = float(max(abs(f_min_theory - body_freq), abs(f_max_theory - body_freq)))
    window = stft_window_metrics(
        rotor_frequency_hz=rotor_frequency,
        micro_doppler_max_hz=micro_max,
        sampling_rate_hz=fs,
        stft_window_size=int(cfg["stft_window_size"]),
    )
    observed = frequency_profile_metrics(f_axis, s_db)

    ratio = omega_theta_ratio(degree_rad)
    omega = float(2.0 * np.pi * rotor_frequency)
    omega_h = omega / ratio
    omega_theta = omega
    sample_id = f"{class_id}_{sample_index:04d}"
    image_rel = Path("images") / class_id / f"{sample_id}.png"
    tensor_rel = Path("tensors") / class_id / f"{sample_id}.npz"

    metadata = {
        "sample_id": sample_id,
        "class_id": class_id,
        "image_path": str(image_rel),
        "tensor_path": str(tensor_rel),
        "scene_name": str(cfg["scene_name"]),
        "scene_source": scene_source,
        "scene_merge_shapes": bool(cfg.get("scene_merge_shapes", False)),
        "body_trajectory_model": str(body_path["model"]),
        "etoile_trajectory_speed_mode": str(body_path["speed_mode"]),
        "etoile_trajectory_start_fraction": body_path["start_fraction"],
        "etoile_trajectory_start_distance_m": body_path["start_distance_m"],
        "etoile_trajectory_speed_m_s": body_path["speed_m_s"],
        "etoile_trajectory_path_length_m": body_path["path_length_m"],
        "etoile_trajectory_control_points_json": json.dumps(np.asarray(body_path["control_points"]).tolist()),
        "carrier_frequency_hz": float(cfg["carrier_frequency_hz"]),
        "sampling_rate_hz": fs,
        "num_snapshots": num_snapshots,
        "snapshot_duration_s": num_snapshots / fs,
        "stft_window_size": int(cfg["stft_window_size"]),
        "stft_overlap": int(cfg["stft_overlap"]),
        "stft_nfft": int(cfg["stft_nfft"]),
        "stft_window_duration_s": window["stft_window_duration_s"],
        "stft_frequency_resolution_hz": window["stft_frequency_resolution_hz"],
        "rotor_frequency_hz": rotor_frequency,
        "rotor_period_s": window["rotor_period_s"],
        "omega_rad_s": omega,
        "omega_h_rad_s": omega_h,
        "omega_theta_rad_s": omega_theta,
        "omega_theta_over_omega_h": ratio,
        "degree": float(spec.degree),
        "degree_rad": degree_rad,
        "body_speed_m_s": float(spec.body_speed_m_s),
        "body_velocity_x": float(body_velocity0[0]),
        "body_velocity_y": float(body_velocity0[1]),
        "body_velocity_z": float(body_velocity0[2]),
        "body_acceleration_x": 0.0,
        "body_acceleration_y": 0.0,
        "body_acceleration_z": 0.0,
        "blade_radius_m": blade_radius,
        "num_uavs": num_uavs,
        "num_rotors": num_rotors,
        "num_blades_per_rotor": num_blades,
        "points_per_blade": points_per_blade,
        "num_scatterers": n_scatterers,
        "doppler_body_theory_hz": body_freq,
        "micro_doppler_max_theory_hz": micro_max,
        "doppler_support_min_theory_hz": f_min_theory,
        "doppler_support_max_theory_hz": f_max_theory,
        "stft_support_min_observed_hz": observed["stft_support_min_observed_hz"],
        "stft_support_max_observed_hz": observed["stft_support_max_observed_hz"],
        "stft_peak_observed_hz": observed["stft_peak_observed_hz"],
        "window_ratio_Twin_over_Trot": window["window_ratio_Twin_over_Trot"],
        "window_strict_metric": window["window_strict_metric"],
        "window_check_pass": window["window_check_pass"],
        "random_seed": seed,
        "noise_snr_db": noise_snr,
        "created_time": utc_now_iso(),
        "initial_body_position_x": float(body_position0[0]),
        "initial_body_position_y": float(body_position0[1]),
        "initial_body_position_z": float(body_position0[2]),
        "initial_rotor_phase_rad": float(initial_phase),
        "bs_position_x": float(cfg["bs_position_x"]),
        "bs_position_y": float(cfg["bs_position_y"]),
        "bs_position_z": float(cfg["bs_position_z"]),
        "scene_channel_model": "sionna_rt_pathsolver",
        "rt_solver": "sionna.rt.PathSolver",
        "rt_max_depth": int(cfg.get("rt_max_depth", 2)),
        "rt_los": bool(cfg.get("rt_los", True)),
        "rt_specular_reflection": bool(cfg.get("rt_specular_reflection", True)),
        "rt_diffuse_reflection": bool(cfg.get("rt_diffuse_reflection", False)),
        "rt_diffraction": bool(cfg.get("rt_diffraction", False)),
        "rt_refraction": bool(cfg.get("rt_refraction", False)),
        "rt_snapshot_stride": stride,
        "rt_snapshots_solved": int(len(solved_indices)),
        "rt_elapsed_s": rt_elapsed,
        "rt_total_valid_paths": int(np.sum(path_counts_solved)),
        "rt_min_valid_paths_per_solved_snapshot": int(np.min(np.sum(path_counts_solved, axis=1))),
        "rt_max_valid_paths_per_solved_snapshot": int(np.max(np.sum(path_counts_solved, axis=1))),
        "rt_cir_sampling_frequency_hz": float(cfg.get("rt_cir_sampling_frequency_hz", 122.88e6)),
    }

    save_stft_image(
        s_db,
        f_axis,
        root / image_rel,
        f_min_hz=float(cfg["doppler_plot_min_hz"]),
        f_max_hz=float(cfg["doppler_plot_max_hz"]),
        dynamic_range_db=float(cfg["stft_dynamic_range_db"]),
    )
    np.savez_compressed(
        root / tensor_rel,
        signal_clean=signal_clean,
        signal_noisy=signal_noisy,
        csi_one_way=csi_one_way,
        return_per_scatterer=return_per_scatterer,
        S_complex=s_complex,
        S_dB=s_db,
        f_axis=f_axis,
        t_axis=t_axis,
        positions=traj["positions"],
        velocities=traj["velocities"],
        rotor_centers=traj["rotor_centers"],
        monostatic_freq_theory=freqs,
        weights=weights.astype(np.float32),
        radii=traj["radii"],
        scatterer_type_codes=traj["scatterer_type_codes"],
        rotor_ids=traj["rotor_ids"],
        blade_phase_offsets=blade_phase_offsets.astype(np.float32),
        body_positions=np.asarray(body_path["positions"], dtype=np.float32),
        body_velocities=np.asarray(body_path["velocities"], dtype=np.float32),
        uav_positions_m=uav_positions_m,
        uav_velocities_m_s=uav_velocities_m_s,
        uav_speeds_m_s=uav_speeds_m_s,
        uav_ids=uav_ids,
        etoile_control_points_m=np.asarray(body_path["control_points"], dtype=np.float32),
        etoile_path_distance_m=np.asarray(body_path["distances_m"], dtype=np.float32),
        path_counts=path_counts,
        rt_solved_indices=solved_indices,
        rt_csi_one_way_solved=h_solved,
        rt_path_counts_solved=path_counts_solved,
        metadata_json=np.asarray(json.dumps(metadata, ensure_ascii=False)),
        labels_json=np.asarray(json.dumps(traj["labels"], ensure_ascii=False)),
        scene_source=np.asarray(scene_source),
    )
    metadata["sample_elapsed_s"] = time.perf_counter() - sample_start
    return metadata


def write_metadata_md(root: Path, rows: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    counts = {class_id: sum(1 for row in rows if row["class_id"] == class_id) for class_id in RT_CLASS_SPECS}
    lines = [
        "# Sionna RT UAV STFT Dataset Metadata Summary",
        "",
        f"- Total samples: `{len(rows)}`",
        "- Channel model: `sionna_rt_pathsolver`",
        "- Important: this dataset calls `sionna.rt.PathSolver` for every configured RT snapshot.",
        f"- RT snapshot stride: `{cfg.get('rt_snapshot_stride', 1)}`",
        f"- RT max depth: `{cfg.get('rt_max_depth', 2)}`",
        "",
        "## Class Counts",
        "",
        "| class_id | samples | degree | body speed [m/s] |",
        "| --- | ---: | ---: | ---: |",
    ]
    for class_id, spec in RT_CLASS_SPECS.items():
        lines.append(f"| `{class_id}` | {counts[class_id]} | {spec.degree} | {spec.body_speed_m_s} |")
    if rows:
        lines.extend(["", "## First Sample Snapshot", ""])
        for key in RT_FIELDNAMES:
            if key in rows[0]:
                lines.append(f"- `{key}`: `{rows[0][key]}`")
    (root / "database" / "metadata.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate UAV STFT samples using Sionna RT PathSolver.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "outputs" / "dataset")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "etoile.yaml")
    parser.add_argument("--samples-per-class", type=int, default=None)
    parser.add_argument("--classes", nargs="*", default=list(RT_CLASS_SPECS))
    parser.add_argument("--start-index", type=int, default=None, help="First sample index to generate, inclusive.")
    parser.add_argument("--end-index", type=int, default=None, help="Last sample index to generate, inclusive.")
    parser.add_argument("--snapshot-override", type=int, default=None, help="Testing only: override num_snapshots.")
    parser.add_argument("--rt-snapshot-stride", type=int, default=None)
    parser.add_argument("--max-new-samples", type=int, default=None, help="Stop after writing this many new samples.")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    args.classes = expand_class_args(args.classes)
    cfg = resolve_config_paths(read_simple_yaml(args.config), args.config)
    if args.samples_per_class is not None:
        cfg["samples_per_class"] = int(args.samples_per_class)
    if args.rt_snapshot_stride is not None:
        cfg["rt_snapshot_stride"] = int(args.rt_snapshot_stride)
    if (args.start_index is None) ^ (args.end_index is None):
        parser.error("--start-index and --end-index must be provided together.")
    if args.start_index is not None and args.end_index is not None:
        if args.start_index < 0:
            parser.error("--start-index must be >= 0.")
        if args.end_index < args.start_index:
            parser.error("--end-index must be >= --start-index.")
        sample_indices = range(int(args.start_index), int(args.end_index) + 1)
    else:
        sample_indices = range(int(cfg["samples_per_class"]))

    root = args.root
    ensure_dirs(root)
    manifest_path = root / "database" / "manifest.jsonl"
    metadata_path = root / "database" / "metadata.csv"
    timing_path = root / "database" / "timing.csv"

    rows: list[dict[str, Any]] = []
    if args.resume and metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))
    done = {row["sample_id"] for row in rows}
    write_rt_manifest(manifest_path, rows)

    total = len(sample_indices) * len(args.classes)
    completed = len(done)
    new_samples = 0
    for class_id in args.classes:
        if class_id not in RT_CLASS_SPECS:
            raise ValueError(f"Unknown class: {class_id}")
        for sample_index in sample_indices:
            if args.max_new_samples is not None and new_samples >= int(args.max_new_samples):
                break
            sample_id = f"{class_id}_{sample_index:04d}"
            if sample_id in done:
                continue
            print(f"[{completed + 1}/{total}] generating {sample_id}", flush=True)
            row = generate_case(
                cfg=cfg,
                root=root,
                class_id=class_id,
                sample_index=sample_index,
                snapshot_override=args.snapshot_override,
            )
            rows.append(row)
            write_rt_metadata_csv(metadata_path, rows)
            write_timing_csv(timing_path, rows)
            write_rt_manifest(manifest_path, rows)
            write_metadata_md(root, rows, cfg)
            completed += 1
            new_samples += 1
        if args.max_new_samples is not None and new_samples >= int(args.max_new_samples):
            break

    write_rt_metadata_csv(metadata_path, rows)
    write_timing_csv(timing_path, rows)
    write_rt_manifest(manifest_path, rows)
    write_metadata_md(root, rows, cfg)
    print(f"Done. Samples: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

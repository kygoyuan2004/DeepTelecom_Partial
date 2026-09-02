#!/usr/bin/env python3
"""UAV point-scatterer motion utilities for the standalone STFT dataset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


SPEED_OF_LIGHT = 299_792_458.0


@dataclass(frozen=True)
class ClassSpec:
    class_id: str
    degree: float
    body_speed_m_s: float


CLASS_SPECS: dict[str, ClassSpec] = {
    "pitch30_v10": ClassSpec("pitch30_v10", 30.0, 10.0),
    "pitch45_v10": ClassSpec("pitch45_v10", 45.0, 10.0),
    "level_v0": ClassSpec("level_v0", 0.0, 0.0),
}


def rotation_y(theta_rad: float) -> np.ndarray:
    c = float(np.cos(theta_rad))
    s = float(np.sin(theta_rad))
    return np.asarray(
        [
            [c, 0.0, s],
            [0.0, 1.0, 0.0],
            [-s, 0.0, c],
        ],
        dtype=np.float64,
    )


def rotor_offsets(num_rotors: int, arm_length_m: float) -> np.ndarray:
    if num_rotors != 4:
        raise ValueError("This dataset generator currently supports exactly 4 rotors.")
    arm = float(arm_length_m)
    return np.asarray(
        [
            [arm, arm, 0.0],
            [-arm, arm, 0.0],
            [-arm, -arm, 0.0],
            [arm, -arm, 0.0],
        ],
        dtype=np.float64,
    )


def omega_theta_ratio(theta_rad: float) -> float:
    cos_theta = float(np.cos(theta_rad))
    if cos_theta <= 0.0:
        raise ValueError("Force-balance tilt angle must satisfy cos(theta) > 0.")
    return float(1.0 / np.sqrt(cos_theta))


def scatterer_count(num_rotors: int, num_blades_per_rotor: int, points_per_blade: int) -> int:
    return int(1 + num_rotors * num_blades_per_rotor * points_per_blade)


def build_default_weights(
    num_rotors: int,
    num_blades_per_rotor: int,
    points_per_blade: int,
    rng: np.random.Generator,
    jitter_fraction: float,
) -> np.ndarray:
    n = scatterer_count(num_rotors, num_blades_per_rotor, points_per_blade)
    weights = np.empty(n, dtype=np.float64)
    weights[0] = 1.0
    blade_total_weight_per_rotor = 0.18
    blade_point_weight = blade_total_weight_per_rotor / max(1, points_per_blade)
    weights[1:] = blade_point_weight
    if jitter_fraction > 0.0:
        jitter = rng.uniform(1.0 - jitter_fraction, 1.0 + jitter_fraction, size=n)
        weights *= np.maximum(jitter, 1e-3)
    return weights


def scatterer_trajectories(
    *,
    num_snapshots: int,
    sampling_rate_hz: float,
    body_position0: np.ndarray,
    body_velocity0: np.ndarray,
    body_acceleration: np.ndarray,
    degree_rad: float,
    rotor_frequency_hz: float,
    blade_radius_m: float,
    rotor_arm_length_m: float,
    num_rotors: int,
    num_blades_per_rotor: int,
    points_per_blade: int,
    initial_rotor_phase: float,
    blade_phase_offsets: np.ndarray | None = None,
) -> dict[str, Any]:
    """Generate body plus tilted rotor-blade point-scatterer positions and velocities."""

    t = np.arange(int(num_snapshots), dtype=np.float64) / float(sampling_rate_hz)
    body_position0 = np.asarray(body_position0, dtype=np.float64)
    body_velocity0 = np.asarray(body_velocity0, dtype=np.float64)
    body_acceleration = np.asarray(body_acceleration, dtype=np.float64)
    body_positions = body_position0[None, :] + t[:, None] * body_velocity0[None, :] + 0.5 * (t[:, None] ** 2) * body_acceleration[None, :]
    body_velocities = body_velocity0[None, :] + t[:, None] * body_acceleration[None, :]

    n_scatterers = scatterer_count(num_rotors, num_blades_per_rotor, points_per_blade)
    positions = np.empty((len(t), n_scatterers, 3), dtype=np.float32)
    velocities = np.empty((len(t), n_scatterers, 3), dtype=np.float32)
    rotor_centers = np.empty((len(t), num_rotors, 3), dtype=np.float32)
    labels: list[str] = ["body"]
    radii = np.zeros(n_scatterers, dtype=np.float32)
    scatterer_type_codes = np.zeros(n_scatterers, dtype=np.int32)
    rotor_ids = np.full(n_scatterers, -1, dtype=np.int32)

    positions[:, 0, :] = body_positions.astype(np.float32)
    velocities[:, 0, :] = body_velocities.astype(np.float32)

    r_body_to_world = rotation_y(degree_rad)
    offsets_world = rotor_offsets(num_rotors, rotor_arm_length_m) @ r_body_to_world.T
    centers = body_positions[:, None, :] + offsets_world[None, :, :]
    rotor_centers[:] = centers.astype(np.float32)

    omega = 2.0 * np.pi * float(rotor_frequency_hz)
    radial_samples = (
        np.linspace(1.0, points_per_blade, points_per_blade, dtype=np.float64)
        / max(1, points_per_blade)
        * float(blade_radius_m)
    )
    if blade_phase_offsets is None:
        blade_phase_offsets = np.zeros((num_rotors, num_blades_per_rotor), dtype=np.float64)
    blade_phase_offsets = np.asarray(blade_phase_offsets, dtype=np.float64)

    idx = 1
    for rotor_idx in range(num_rotors):
        rotor_phase = initial_rotor_phase + rotor_idx * np.pi / 2.0
        for blade_idx in range(num_blades_per_rotor):
            blade_phase = 2.0 * np.pi * blade_idx / num_blades_per_rotor + blade_phase_offsets[rotor_idx, blade_idx]
            phi = omega * t + rotor_phase + blade_phase
            cos_phi = np.cos(phi)
            sin_phi = np.sin(phi)
            for rho in radial_samples:
                rel_local = np.stack([rho * cos_phi, rho * sin_phi, np.zeros_like(t)], axis=1)
                vel_local = np.stack([-omega * rho * sin_phi, omega * rho * cos_phi, np.zeros_like(t)], axis=1)
                rel_world = rel_local @ r_body_to_world.T
                vel_world = vel_local @ r_body_to_world.T
                positions[:, idx, :] = (centers[:, rotor_idx, :] + rel_world).astype(np.float32)
                velocities[:, idx, :] = (body_velocities + vel_world).astype(np.float32)
                labels.append(f"rotor{rotor_idx}_blade{blade_idx}_rho{rho:.5f}")
                radii[idx] = float(rho)
                scatterer_type_codes[idx] = 1
                rotor_ids[idx] = rotor_idx
                idx += 1

    return {
        "t": t.astype(np.float32),
        "positions": positions,
        "velocities": velocities,
        "rotor_centers": rotor_centers,
        "labels": labels,
        "radii": radii,
        "scatterer_type_codes": scatterer_type_codes,
        "rotor_ids": rotor_ids,
    }


def monostatic_doppler_theory(
    positions: np.ndarray,
    velocities: np.ndarray,
    bs_position: np.ndarray,
    carrier_frequency_hz: float,
) -> np.ndarray:
    wavelength = SPEED_OF_LIGHT / float(carrier_frequency_hz)
    bs = np.asarray(bs_position, dtype=np.float64)
    pos = np.asarray(positions, dtype=np.float64)
    vel = np.asarray(velocities, dtype=np.float64)
    los = pos - bs[None, None, :]
    los_norm = np.linalg.norm(los, axis=2, keepdims=True)
    los_unit = los / np.maximum(los_norm, 1e-12)
    range_rate = np.sum(vel * los_unit, axis=2)
    return (-2.0 * range_rate / wavelength).astype(np.float32)


#!/usr/bin/env python3
"""Add and validate explicit per-UAV position, velocity, and speed arrays."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np


REQUIRED_UAV_KEYS = (
    "uav_positions_m",
    "uav_velocities_m_s",
    "uav_speeds_m_s",
    "uav_ids",
)


def metadata_tensor_paths(root: Path) -> list[Path]:
    metadata_path = root / "database" / "metadata.csv"
    if not metadata_path.exists():
        raise SystemExit(f"Metadata file not found: {metadata_path}")
    with metadata_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    paths = [root / row["tensor_path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise SystemExit("metadata.csv contains duplicate tensor_path values")
    return paths


def expected_uav_arrays(arrays: dict[str, np.ndarray], path: Path) -> dict[str, np.ndarray]:
    if "body_positions" not in arrays or "body_velocities" not in arrays:
        raise ValueError(f"{path}: missing body_positions/body_velocities")
    positions = np.asarray(arrays["body_positions"], dtype=np.float32)
    velocities = np.asarray(arrays["body_velocities"], dtype=np.float32)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError(f"{path}: body_positions must have shape [time,3], got {positions.shape}")
    if velocities.shape != positions.shape:
        raise ValueError(
            f"{path}: body_velocities shape {velocities.shape} does not match {positions.shape}"
        )
    if "metadata_json" in arrays:
        metadata = json.loads(str(arrays["metadata_json"]))
        if int(metadata.get("num_uavs", 1)) != 1:
            raise ValueError(f"{path}: only the current one-UAV samples can be upgraded safely")
    uav_positions = positions[:, None, :]
    uav_velocities = velocities[:, None, :]
    return {
        "uav_positions_m": uav_positions,
        "uav_velocities_m_s": uav_velocities,
        "uav_speeds_m_s": np.linalg.norm(uav_velocities, axis=-1).astype(np.float32),
        "uav_ids": np.asarray(["uav_000"]),
    }


def validate_uav_arrays(
    arrays: dict[str, np.ndarray],
    expected: dict[str, np.ndarray],
    path: Path,
) -> None:
    missing = [key for key in REQUIRED_UAV_KEYS if key not in arrays]
    if missing:
        raise ValueError(f"{path}: missing explicit per-UAV keys: {missing}")
    for key in REQUIRED_UAV_KEYS:
        actual = np.asarray(arrays[key])
        wanted = np.asarray(expected[key])
        if actual.shape != wanted.shape:
            raise ValueError(f"{path}: {key} shape {actual.shape}, expected {wanted.shape}")
        if actual.dtype.kind in "fci":
            if not np.allclose(actual, wanted, rtol=1e-6, atol=1e-6):
                raise ValueError(f"{path}: {key} values do not match body trajectory")
        elif not np.array_equal(actual, wanted):
            raise ValueError(f"{path}: {key} values do not match expected UAV ids")


def process_npz(path: Path, *, verify_only: bool) -> bool:
    if not path.exists():
        raise ValueError(f"Tensor file not found: {path}")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    expected = expected_uav_arrays(arrays, path)
    if all(key in arrays for key in REQUIRED_UAV_KEYS):
        validate_uav_arrays(arrays, expected, path)
        return False
    if verify_only:
        missing = [key for key in REQUIRED_UAV_KEYS if key not in arrays]
        raise ValueError(f"{path}: missing keys in verify-only mode: {missing}")

    arrays.update(expected)
    temporary = path.with_name(f".{path.name}.uav-upgrade.tmp.npz")
    try:
        np.savez_compressed(temporary, **arrays)
        with np.load(temporary, allow_pickle=False) as check:
            check_arrays = {key: check[key] for key in REQUIRED_UAV_KEYS}
        validate_uav_arrays(check_arrays, expected, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add or validate explicit [time,uav,xyz] kinematics arrays in dataset NPZ files."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    paths = metadata_tensor_paths(root)
    upgraded = 0
    errors: list[str] = []
    for index, path in enumerate(paths, start=1):
        try:
            upgraded += int(process_npz(path, verify_only=args.verify_only))
        except Exception as exc:
            errors.append(str(exc))
        if index % 100 == 0 or index == len(paths):
            print(f"Checked {index}/{len(paths)} tensor files; upgraded={upgraded}", flush=True)
    if errors:
        preview = "\n".join(errors[:20])
        raise SystemExit(f"Per-UAV kinematics validation failed ({len(errors)} files):\n{preview}")
    action = "Verified" if args.verify_only else "Checked/upgraded"
    print(f"{action} {len(paths)} tensor files; newly upgraded={upgraded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

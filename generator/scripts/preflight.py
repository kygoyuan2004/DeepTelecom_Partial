#!/usr/bin/env python3
"""Validate the portable generator, dependencies, GPU, and configured RT scene."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "etoile.yaml"


def reexec_in_selected_python() -> None:
    """Honor the same interpreter override used by the smoke-test wrapper."""

    requested = os.environ.get("DEEPTELECOM_PYTHON", "").strip()
    local_python = PACKAGE_ROOT / ".conda-env" / "bin" / "python"
    candidate = Path(requested).expanduser() if requested else local_python
    if requested and not candidate.is_file():
        raise SystemExit(f"DEEPTELECOM_PYTHON is not a Python executable: {candidate}")
    if not candidate.is_file():
        return
    try:
        already_selected = candidate.resolve().samefile(Path(sys.executable).resolve())
    except OSError:
        already_selected = False
    if not already_selected:
        os.execv(str(candidate), [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]])


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def read_simple_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def gpu_rows() -> list[list[str]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("nvidia-smi was not found; an NVIDIA GPU is required") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"nvidia-smi failed: {exc.stderr.strip()}") from exc
    return [
        [part.strip() for part in line.split(",")]
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def main() -> int:
    reexec_in_selected_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--skip-scene-load",
        action="store_true",
        help="Check configuration, imports, and GPU only; do not load the RT scene.",
    )
    args = parser.parse_args()

    config_path = args.config.expanduser().resolve()
    if not config_path.is_file():
        raise SystemExit(f"Configuration file not found: {config_path}")
    cfg = read_simple_yaml(config_path)

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.environ.get("DEEPTELECOM_GPU_ID", "0"))
    if sys.version_info[:2] != (3, 11):
        print(
            f"WARNING: tested with Python 3.11, current={sys.version.split()[0]}",
            file=sys.stderr,
        )

    required_imports = ("numpy", "scipy", "PIL", "matplotlib", "tensorflow", "sionna", "sionna.rt")
    failures: list[str] = []
    for name in required_imports:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    if failures:
        raise SystemExit("Dependency import failures:\n" + "\n".join(failures))

    rows = gpu_rows()
    if not rows:
        raise SystemExit("nvidia-smi did not report any GPUs")

    scene_xml = cfg.get("scene_xml_path", "")
    scene_name = cfg.get("scene_name", "etoile")
    if scene_xml:
        candidate = Path(scene_xml).expanduser()
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        if not candidate.is_file():
            raise SystemExit(f"Configured scene XML is missing: {candidate.resolve()}")
        scene_ref: object = str(candidate.resolve())
        logical_scene = f"scene_xml:{candidate.name}"
    else:
        import sionna

        if not hasattr(sionna.rt.scene, scene_name):
            raise SystemExit(f"Sionna RT has no built-in scene named {scene_name!r}")
        scene_ref = getattr(sionna.rt.scene, scene_name)
        logical_scene = f"sionna.rt.scene.{scene_name}"

    print(f"Python: {sys.executable} ({sys.version.split()[0]})")
    for name in ("sionna", "sionna-rt", "tensorflow", "mitsuba", "drjit", "numpy", "scipy"):
        print(f"{name}: {package_version(name)}")
    print(f"RT scene: {logical_scene}")
    print(f"NVIDIA GPUs: {len(rows)}")
    for row in rows:
        print("  " + " | ".join(row))

    if not args.skip_scene_load:
        from sionna.rt import load_scene

        try:
            scene = load_scene(scene_ref, merge_shapes=True)
        except TypeError:
            scene = load_scene(scene_ref)
        print(f"Sionna scene load: OK ({len(scene.objects)} object(s))")

    run_root = PACKAGE_ROOT / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".write-test-", dir=run_root, delete=True):
        pass
    print("Writable run directory: OK")
    print("Preflight: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stream DeepTelecom v1 WebDataset TARs with only tarfile plus NumPy."""

from __future__ import annotations

import argparse
from glob import glob
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tarfile
from typing import Dict, Iterator, List, MutableSet, Optional, Sequence, Tuple
from zipfile import BadZipFile

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised only without NumPy
    raise SystemExit("NumPy is required: python -m pip install numpy") from exc


MEMBER_RE = re.compile(r"^(DTUAV-V1-\d{6})\.(npz|png|json)$")
HEX_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SHARD_NAME_RE = re.compile(r"^shard-(\d{5})\.tar$")
MAX_SIDECAR_BYTES = 16 * 1024 * 1024


class DatasetFormatError(RuntimeError):
    """A shard does not implement the DeepTelecom v1 sample contract."""


def _json_no_duplicate_keys(pairs: List[Tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetFormatError(f"duplicate JSON key in sample sidecar: {key}")
        result[key] = value
    return result


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise DatasetFormatError(f"cannot read TAR member: {member.name}")
    payload = stream.read(member.size + 1)
    if len(payload) != member.size:
        raise DatasetFormatError(f"short TAR member: {member.name}")
    return payload


def _mapping(value: object, label: str, sample_id: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise DatasetFormatError(f"{label} must be an object for {sample_id}")
    return value


def _validate_payload_record(
    metadata: Dict[str, object],
    sample_id: str,
    shard_name: str,
    npz_bytes: bytes,
    png_bytes: bytes,
) -> None:
    if metadata.get("global_sample_id") != sample_id:
        raise DatasetFormatError(f"sidecar ID mismatch for {sample_id}")
    if metadata.get("target_shard") != f"data/v1/shards/{shard_name}":
        raise DatasetFormatError(f"target_shard mismatch for {sample_id}")
    members = _mapping(metadata.get("members"), "members", sample_id)
    if members != {ext: f"{sample_id}.{ext}" for ext in ("npz", "png", "json")}:
        raise DatasetFormatError(f"member map mismatch for {sample_id}")

    files = _mapping(metadata.get("files"), "files", sample_id)
    for extension, payload in (("npz", npz_bytes), ("png", png_bytes)):
        record = _mapping(files.get(extension), f"files.{extension}", sample_id)
        expected_size = record.get("bytes")
        expected_sha = record.get("sha256")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool):
            raise DatasetFormatError(f"invalid files.{extension}.bytes for {sample_id}")
        if not isinstance(expected_sha, str) or HEX_SHA_RE.fullmatch(expected_sha) is None:
            raise DatasetFormatError(f"invalid files.{extension}.sha256 for {sample_id}")
        if len(payload) != expected_size:
            raise DatasetFormatError(f"{extension.upper()} size mismatch for {sample_id}")
        if hashlib.sha256(payload).hexdigest() != expected_sha:
            raise DatasetFormatError(f"{extension.upper()} SHA256 mismatch for {sample_id}")


def _group_members(archive: tarfile.TarFile) -> Dict[str, Dict[str, tarfile.TarInfo]]:
    grouped: Dict[str, Dict[str, tarfile.TarInfo]] = {}
    names: MutableSet[str] = set()
    for member in archive.getmembers():
        if not member.isfile():
            raise DatasetFormatError(f"non-regular TAR member: {member.name}")
        if member.name in names:
            raise DatasetFormatError(f"duplicate TAR member: {member.name}")
        names.add(member.name)
        match = MEMBER_RE.fullmatch(member.name)
        if match is None:
            raise DatasetFormatError(f"unexpected TAR member name: {member.name}")
        sample_id, extension = match.groups()
        bucket = grouped.setdefault(sample_id, {})
        if extension in bucket:
            raise DatasetFormatError(f"duplicate {extension} member for {sample_id}")
        bucket[extension] = member
    if not grouped:
        raise DatasetFormatError("empty shard")
    for sample_id, bucket in grouped.items():
        if set(bucket) != {"npz", "png", "json"}:
            raise DatasetFormatError(f"incomplete NPZ/PNG/JSON triple for {sample_id}")
    return grouped


def _load_npz(payload: bytes, sample_id: str) -> Dict[str, np.ndarray]:
    try:
        with np.load(BytesIO(payload), allow_pickle=False) as archive:
            # Materialize inside the context. Accessing every array also rejects object
            # dtypes that would otherwise require pickle.
            return {name: archive[name] for name in archive.files}
    except (OSError, ValueError, KeyError, EOFError, BadZipFile) as exc:
        raise DatasetFormatError(f"invalid safe NPZ payload for {sample_id}: {exc}") from exc


def iter_samples(
    shard_paths: Sequence[Path], limit: Optional[int] = None
) -> Iterator[Dict[str, object]]:
    """Yield validated samples with ``tensor``, ``png``, and ``metadata`` fields.

    NPZ arrays are eagerly materialized with ``allow_pickle=False``. PNG data remains
    encoded bytes so callers may choose Pillow, OpenCV, or another decoder.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative or None")
    if limit == 0:
        return

    yielded = 0
    globally_seen: MutableSet[str] = set()
    for raw_path in shard_paths:
        shard_path = Path(raw_path).expanduser()
        if shard_path.is_symlink() or not shard_path.is_file():
            raise DatasetFormatError(f"shard is missing, non-regular, or a symlink: {shard_path}")
        if SHARD_NAME_RE.fullmatch(shard_path.name) is None:
            raise DatasetFormatError(f"unexpected shard filename: {shard_path.name}")
        try:
            with tarfile.open(shard_path, mode="r:*") as archive:
                groups = _group_members(archive)
                overlap = set(groups).intersection(globally_seen)
                if overlap:
                    raise DatasetFormatError(f"sample ID appears in multiple shards: {min(overlap)}")
                globally_seen.update(groups)

                for sample_id in sorted(groups):
                    members = groups[sample_id]
                    json_member = members["json"]
                    if json_member.size > MAX_SIDECAR_BYTES:
                        raise DatasetFormatError(f"oversized JSON sidecar for {sample_id}")
                    raw_json = _read_member(archive, json_member)
                    try:
                        metadata = json.loads(
                            raw_json.decode("utf-8", errors="strict"),
                            object_pairs_hook=_json_no_duplicate_keys,
                        )
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise DatasetFormatError(f"invalid JSON for {sample_id}: {exc}") from exc
                    if not isinstance(metadata, dict):
                        raise DatasetFormatError(f"JSON sidecar is not an object for {sample_id}")

                    npz_bytes = _read_member(archive, members["npz"])
                    png_bytes = _read_member(archive, members["png"])
                    _validate_payload_record(
                        metadata, sample_id, shard_path.name, npz_bytes, png_bytes
                    )
                    arrays = _load_npz(npz_bytes, sample_id)
                    yield {
                        "sample_id": sample_id,
                        "tensor": arrays,
                        "png": png_bytes,
                        "metadata": metadata,
                        "shard": str(shard_path),
                    }
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
        except (tarfile.TarError, OSError) as exc:
            raise DatasetFormatError(f"cannot read shard {shard_path}: {exc}") from exc


def _expand_shards(patterns: Sequence[str], data_dir: Path) -> List[Path]:
    candidates: List[Path] = []
    if patterns:
        for pattern in patterns:
            matches = [Path(value) for value in glob(pattern)]
            if matches:
                candidates.extend(matches)
            else:
                candidates.append(Path(pattern))
    else:
        candidates.extend(data_dir.expanduser().glob("shard-*.tar"))

    unique: Dict[str, Path] = {}
    for path in candidates:
        resolved = path.expanduser().resolve(strict=False)
        unique[str(resolved)] = path
    result = sorted(unique.values(), key=lambda value: value.name)
    if not result:
        raise DatasetFormatError(f"no shards found under {data_dir}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="*", help="TAR files or glob patterns")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/v1/shards"),
        help="used when no shard paths are supplied",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="maximum samples to inspect (default: 5; use 0 for all)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit < 0:
        raise DatasetFormatError("--limit must be non-negative")
    paths = _expand_shards(args.shards, args.data_dir)
    effective_limit = None if args.limit == 0 else args.limit
    count = 0
    for sample in iter_samples(paths, limit=effective_limit):
        metadata = sample["metadata"]
        tensor = sample["tensor"]
        assert isinstance(metadata, dict)
        assert isinstance(tensor, dict)
        print(
            json.dumps(
                {
                    "sample_id": sample["sample_id"],
                    "class_id": metadata.get("class_id"),
                    "tensor_schema_id": metadata.get("tensor_schema_id"),
                    "npz_keys": sorted(tensor),
                    "png_bytes": len(sample["png"]),
                    "shard": sample["shard"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        count += 1
    print(f"Loaded {count} sample(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DatasetFormatError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

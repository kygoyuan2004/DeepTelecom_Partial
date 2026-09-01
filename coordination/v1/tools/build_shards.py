#!/usr/bin/env python3
"""Build deterministic DeepTelecom v1 WebDataset TAR shards from an allocation.

This tool never modifies source NPZ/PNG files and never uploads anything.  It
fails closed on plan, source, size, hash, path, ownership, or member mismatch.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable


PLAN_RE = re.compile(r"^dtuav-v1-plan-[0-9a-f]{64}$")
GLOBAL_ID_RE = re.compile(r"^DTUAV-V1-[0-9]{6}$")
SHARD_RE = re.compile(r"^data/v1/shards/shard-[0-9]{5}\.tar$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SERVER_IDS = {"a100", "rtx4090", "rtx3090x4"}
MEMBER_SUFFIXES = ("npz", "png", "json")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def read_jsonl_gzip(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"allocation line {line_number} is not an object")
            rows.append(value)
    return rows


def safe_relative_path(root: Path, relpath: str) -> Path:
    pure = PurePosixPath(relpath)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe relative path: {relpath!r}")
    resolved_root = root.resolve()
    resolved = resolved_root.joinpath(*pure.parts).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path escapes source root: {relpath!r}") from exc
    return resolved


def load_roots(path: Path) -> dict[str, Path]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if "source_roots" in value:
        value = value["source_roots"]
    if not isinstance(value, dict):
        raise ValueError("source roots file must be an object")
    result: dict[str, Path] = {}
    for root_id, root_path in value.items():
        if not isinstance(root_id, str) or not isinstance(root_path, str):
            raise ValueError("source root IDs and paths must be strings")
        path_value = Path(root_path).resolve()
        if not path_value.is_dir():
            raise FileNotFoundError(f"source root not found: {root_id}")
        result[root_id] = path_value
    return result


def require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def validate_row(
    row: dict[str, Any],
    plan_id: str,
    server_id: str,
    roots: dict[str, Path],
) -> tuple[Path, Path]:
    if row.get("plan_id") != plan_id:
        raise ValueError(f"plan_id mismatch for {row.get('source_uid')}")
    if row.get("source_server") != server_id:
        raise ValueError(f"wrong shard owner for {row.get('source_uid')}")
    if row.get("decision") != "accepted":
        raise ValueError("allocation contains a non-accepted row")
    global_id = row.get("global_sample_id")
    if not isinstance(global_id, str) or not GLOBAL_ID_RE.fullmatch(global_id):
        raise ValueError(f"invalid global sample ID: {global_id!r}")
    shard = row.get("target_shard")
    if not isinstance(shard, str) or not SHARD_RE.fullmatch(shard):
        raise ValueError(f"invalid target shard: {shard!r}")
    expected_members = {
        "tensor_member": f"{global_id}.npz",
        "image_member": f"{global_id}.png",
        "json_member": f"{global_id}.json",
    }
    for field, expected in expected_members.items():
        if row.get(field) != expected:
            raise ValueError(f"{field} mismatch for {global_id}")
    root_id = row.get("source_root_id")
    if root_id not in roots:
        raise ValueError(f"unmapped source_root_id: {root_id!r}")
    tensor_path = safe_relative_path(roots[root_id], str(row.get("tensor_relpath", "")))
    image_path = safe_relative_path(roots[root_id], str(row.get("image_relpath", "")))
    for path, size_field, hash_field in (
        (tensor_path, "tensor_size_bytes", "tensor_sha256"),
        (image_path, "image_size_bytes", "image_sha256"),
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_size = row.get(size_field)
        if not isinstance(expected_size, int) or expected_size <= 0:
            raise ValueError(f"invalid {size_field} for {global_id}")
        if path.stat().st_size != expected_size:
            raise ValueError(f"source size mismatch: {path}")
        expected_hash = require_hash(row.get(hash_field), hash_field)
        if sha256_file(path) != expected_hash:
            raise ValueError(f"source hash mismatch: {path}")
    require_hash(row.get("semantic_sha256"), "semantic_sha256")
    return tensor_path, image_path


def sample_sidecar(row: dict[str, Any], plan_id: str) -> bytes:
    value = {
        "sidecar_version": "deeptelecom.sample-sidecar.v1",
        "dataset_id": "KYGOYUAN/DeepTelecom_Partial",
        "dataset_version": "v1.0.0",
        "plan_id": plan_id,
        "global_sample_id": row["global_sample_id"],
        "class_id": row["class_id"],
        "tensor_schema_id": row["tensor_schema_id"],
        "semantic_hash_algorithm": "deeptelecom-array-semantic-sha256-v1",
        "semantic_sha256": row["semantic_sha256"],
        "target_shard": row["target_shard"],
        "members": {
            "npz": row["tensor_member"],
            "png": row["image_member"],
            "json": row["json_member"],
        },
        "files": {
            "npz": {
                "bytes": row["tensor_size_bytes"],
                "sha256": row["tensor_sha256"],
            },
            "png": {
                "bytes": row["image_size_bytes"],
                "sha256": row["image_sha256"],
            },
        },
        "provenance": {
            "source_server": row["source_server"],
            "source_root_id": row["source_root_id"],
            "source_uid": row["source_uid"],
            "original_sample_id": row["original_sample_id"],
            "original_index": row["original_index"],
            "batch_id": row.get("batch_id"),
            "source_schema_id": row["source_schema_id"],
        },
    }
    payload = (canonical_json(value) + "\n").encode("utf-8")
    for forbidden in (b"/workspace/", b"/home/", b"/mnt/", b"file://"):
        if forbidden in payload:
            raise ValueError(f"absolute path leaked into sidecar for {row['global_sample_id']}")
    return payload


def tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = tarfile.REGTYPE
    return info


def add_file(archive: tarfile.TarFile, member: str, path: Path) -> None:
    with path.open("rb") as handle:
        archive.addfile(tar_info(member, path.stat().st_size), handle)


def add_bytes(archive: tarfile.TarFile, member: str, payload: bytes) -> None:
    archive.addfile(tar_info(member, len(payload)), io.BytesIO(payload))


def shard_allocation_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update((canonical_json(row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def verify_tar(path: Path, rows: list[dict[str, Any]], plan_id: str) -> None:
    expected: dict[str, tuple[int, str | None]] = {}
    for row in rows:
        expected[row["tensor_member"]] = (
            row["tensor_size_bytes"],
            row["tensor_sha256"],
        )
        expected[row["image_member"]] = (
            row["image_size_bytes"],
            row["image_sha256"],
        )
        sidecar = sample_sidecar(row, plan_id)
        expected[row["json_member"]] = (len(sidecar), hashlib.sha256(sidecar).hexdigest())
    observed: dict[str, tuple[int, str]] = {}
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            if not member.isfile() or member.name in observed:
                raise ValueError(f"invalid or duplicate TAR member: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot read TAR member: {member.name}")
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
            observed[member.name] = (member.size, digest.hexdigest())
    if set(observed) != set(expected):
        raise ValueError(f"TAR member set mismatch: {path}")
    for name, (size, digest) in expected.items():
        if observed[name] != (size, digest):
            raise ValueError(f"TAR member content mismatch: {name}")


def build_one_shard(
    target: Path,
    rows: list[dict[str, Any]],
    paths: dict[str, tuple[Path, Path]],
    plan_id: str,
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row["global_sample_id"])
    if target.exists():
        verify_tar(target, ordered, plan_id)
    else:
        temporary = target.with_name(f".{target.name}.partial")
        with temporary.open("wb") as raw_handle:
            with tarfile.open(
                fileobj=raw_handle,
                mode="w",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                for row in ordered:
                    tensor_path, image_path = paths[row["source_uid"]]
                    add_file(archive, row["tensor_member"], tensor_path)
                    add_file(archive, row["image_member"], image_path)
                    add_bytes(archive, row["json_member"], sample_sidecar(row, plan_id))
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
        os.replace(temporary, target)
        verify_tar(target, ordered, plan_id)
    return {
        "target_shard": rows[0]["target_shard"],
        "sha256": sha256_file(target),
        "size_bytes": target.stat().st_size,
        "sample_count": len(ordered),
        "member_count": len(ordered) * 3,
        "first_global_sample_id": ordered[0]["global_sample_id"],
        "last_global_sample_id": ordered[-1]["global_sample_id"],
        "allocation_rows_sha256": shard_allocation_hash(ordered),
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--source-roots", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--server-id", choices=sorted(SERVER_IDS), required=True)
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or not PLAN_RE.fullmatch(plan_id):
        raise ValueError("invalid plan_id")
    allocation_sha = sha256_file(args.allocation)
    expected_allocation_sha = plan["allocation_file_sha256"].get(args.server_id)
    if allocation_sha != expected_allocation_sha:
        raise ValueError("allocation file hash does not match plan")
    roots = load_roots(args.source_roots)
    rows = read_jsonl_gzip(args.allocation)
    if not rows:
        raise ValueError("allocation is empty")
    source_paths: dict[str, tuple[Path, Path]] = {}
    global_ids: set[str] = set()
    members: set[str] = set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        paths = validate_row(row, plan_id, args.server_id, roots)
        source_uid = row["source_uid"]
        if source_uid in source_paths:
            raise ValueError(f"duplicate source_uid: {source_uid}")
        source_paths[source_uid] = paths
        if row["global_sample_id"] in global_ids:
            raise ValueError(f"duplicate global_sample_id: {row['global_sample_id']}")
        global_ids.add(row["global_sample_id"])
        for field in ("tensor_member", "image_member", "json_member"):
            if row[field] in members:
                raise ValueError(f"duplicate member name: {row[field]}")
            members.add(row[field])
        grouped[row["target_shard"]].append(row)

    shard_receipts: list[dict[str, Any]] = []
    for shard_name in sorted(grouped):
        target = safe_relative_path(args.output_root, shard_name)
        receipt = build_one_shard(
            target,
            grouped[shard_name],
            source_paths,
            plan_id,
        )
        shard_receipts.append(receipt)
        print(
            f"verified {shard_name} {receipt['sample_count']} samples {receipt['size_bytes']} bytes",
            flush=True,
        )

    receipt_root = args.output_root / "build_receipts" / args.server_id
    jsonl_payload = "".join(canonical_json(row) + "\n" for row in shard_receipts)
    atomic_write(receipt_root / "shards.jsonl", jsonl_payload.encode("utf-8"))
    checksums = "".join(
        f"{row['sha256']}  {row['target_shard']}\n" for row in shard_receipts
    )
    atomic_write(receipt_root / "SHA256SUMS", checksums.encode("utf-8"))
    receipt = {
        "receipt_version": "deeptelecom-build-receipt-v1",
        "created_at_utc": utc_now(),
        "plan_id": plan_id,
        "server_id": args.server_id,
        "allocation_file_sha256": allocation_sha,
        "sample_count": len(rows),
        "shard_count": len(shard_receipts),
        "member_count": len(rows) * 3,
        "total_tar_bytes": sum(row["size_bytes"] for row in shard_receipts),
        "all_local_verified": True,
    }
    atomic_json(receipt_root / "build_receipt.json", receipt)
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

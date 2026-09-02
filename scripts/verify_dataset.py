#!/usr/bin/env python3
"""Verify DeepTelecom v1 files; optionally inspect every TAR sample triple."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
from typing import Dict, Iterable, List, MutableSet, Optional, Tuple


DEFAULT_CHECKSUMS = "checksums/v1/SHA256SUMS"
SHARD_RE = re.compile(r"^data/v1/shards/shard-(\d{5})\.tar$")
MEMBER_RE = re.compile(r"^(DTUAV-V1-\d{6})\.(npz|png|json)$")
SHA_RE = re.compile(r"^([0-9a-fA-F]{64})  ([^\r\n]+)$")
HEX_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK_SIZE = 8 * 1024 * 1024
MAX_SIDECAR_BYTES = 16 * 1024 * 1024


class VerificationError(RuntimeError):
    """The local dataset fails a structural or cryptographic check."""


def _safe_checksum_path(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise VerificationError(f"unsafe path in SHA256SUMS: {value!r}")
    parts = value.split("/")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in parts)
        or path.as_posix() != value
    ):
        raise VerificationError(f"unsafe path in SHA256SUMS: {value!r}")
    return value


def parse_sha256sums(path: Path) -> Dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise VerificationError(f"cannot read SHA256SUMS {path}: {exc}") from exc
    entries: Dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        match = SHA_RE.fullmatch(line)
        if match is None:
            raise VerificationError(f"malformed SHA256SUMS line {line_number}")
        digest, raw_path = match.groups()
        relative = _safe_checksum_path(raw_path)
        if relative in entries:
            raise VerificationError(f"duplicate SHA256SUMS entry: {relative}")
        entries[relative] = digest.lower()
    if not entries:
        raise VerificationError("SHA256SUMS contains no entries")
    return entries


def _local_file(root: Path, relative: str) -> Path:
    target = root / Path(*PurePosixPath(_safe_checksum_path(relative)).parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"checksum path escapes dataset root: {relative}") from exc
    if target.is_symlink():
        raise VerificationError(f"refusing symlink: {relative}")
    return target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_no_duplicate_keys(pairs: List[Tuple[str, object]]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key in sample sidecar: {key}")
        result[key] = value
    return result


def _read_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise VerificationError(f"cannot read TAR member: {member.name}")
    payload = stream.read(member.size + 1)
    if len(payload) != member.size:
        raise VerificationError(f"short TAR member: {member.name}")
    return payload


def _hash_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> Tuple[str, int]:
    stream = archive.extractfile(member)
    if stream is None:
        raise VerificationError(f"cannot read TAR member: {member.name}")
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    if size != member.size:
        raise VerificationError(f"short TAR member: {member.name}")
    return digest.hexdigest(), size


def _require_mapping(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise VerificationError(f"sidecar field {label} must be an object")
    return value


def _validate_sidecar(
    metadata: Dict[str, object],
    sample_id: str,
    expected_shard: str,
    members: Dict[str, tarfile.TarInfo],
    archive: tarfile.TarFile,
) -> None:
    if metadata.get("global_sample_id") != sample_id:
        raise VerificationError(f"sidecar ID mismatch for {sample_id}")
    if metadata.get("target_shard") != expected_shard:
        raise VerificationError(f"sidecar target_shard mismatch for {sample_id}")
    if metadata.get("sidecar_version") != "deeptelecom.sample-sidecar.v1":
        raise VerificationError(f"unsupported sidecar_version for {sample_id}")

    member_map = _require_mapping(metadata.get("members"), "members")
    expected_members = {ext: f"{sample_id}.{ext}" for ext in ("npz", "png", "json")}
    if member_map != expected_members:
        raise VerificationError(f"sidecar member map mismatch for {sample_id}")

    files = _require_mapping(metadata.get("files"), "files")
    for extension in ("npz", "png"):
        file_record = _require_mapping(files.get(extension), f"files.{extension}")
        expected_digest = file_record.get("sha256")
        expected_size = file_record.get("bytes")
        if not isinstance(expected_digest, str) or HEX_SHA_RE.fullmatch(expected_digest) is None:
            raise VerificationError(f"invalid files.{extension}.sha256 for {sample_id}")
        if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
            raise VerificationError(f"invalid files.{extension}.bytes for {sample_id}")
        actual_digest, actual_size = _hash_member(archive, members[extension])
        if actual_size != expected_size or actual_digest != expected_digest:
            raise VerificationError(f"{extension.upper()} payload mismatch for {sample_id}")


def _deep_verify_tar(
    tar_path: Path, relative_path: str, globally_seen: MutableSet[str]
) -> Tuple[int, int]:
    expected_shard = f"data/v1/shards/{tar_path.name}"
    if relative_path != expected_shard:
        raise VerificationError(f"unexpected TAR location for deep verification: {relative_path}")

    try:
        with tarfile.open(tar_path, mode="r:*") as archive:
            grouped: Dict[str, Dict[str, tarfile.TarInfo]] = {}
            names: MutableSet[str] = set()
            for member in archive.getmembers():
                if not member.isfile():
                    raise VerificationError(f"non-regular TAR member in {relative_path}: {member.name}")
                if member.name in names:
                    raise VerificationError(f"duplicate TAR member in {relative_path}: {member.name}")
                names.add(member.name)
                match = MEMBER_RE.fullmatch(member.name)
                if match is None:
                    raise VerificationError(f"unexpected TAR member name: {member.name}")
                sample_id, extension = match.groups()
                group = grouped.setdefault(sample_id, {})
                if extension in group:
                    raise VerificationError(f"duplicate {extension} for {sample_id}")
                group[extension] = member

            if not grouped:
                raise VerificationError(f"empty TAR: {relative_path}")
            if len(names) != 3 * len(grouped):
                raise VerificationError(f"TAR does not contain exactly three members per sample: {relative_path}")
            local_ids = set(grouped)
            overlap = local_ids.intersection(globally_seen)
            if overlap:
                raise VerificationError(f"sample ID appears in multiple TARs: {min(overlap)}")

            for sample_id in sorted(grouped):
                members = grouped[sample_id]
                if set(members) != {"npz", "png", "json"}:
                    raise VerificationError(f"incomplete TAR triple for {sample_id}")
                json_member = members["json"]
                if json_member.size > MAX_SIDECAR_BYTES:
                    raise VerificationError(f"oversized JSON sidecar for {sample_id}")
                raw_json = _read_member_bytes(archive, json_member)
                try:
                    metadata = json.loads(
                        raw_json.decode("utf-8", errors="strict"),
                        object_pairs_hook=_json_no_duplicate_keys,
                    )
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise VerificationError(f"invalid JSON sidecar for {sample_id}: {exc}") from exc
                if not isinstance(metadata, dict):
                    raise VerificationError(f"JSON sidecar is not an object for {sample_id}")
                _validate_sidecar(metadata, sample_id, expected_shard, members, archive)

            globally_seen.update(local_ids)
            return len(grouped), len(names)
    except (tarfile.TarError, OSError) as exc:
        raise VerificationError(f"cannot inspect {relative_path}: {exc}") from exc


def _select_entries(
    entries: Dict[str, str],
    shards_only: bool,
    start: Optional[int],
    end: Optional[int],
) -> List[Tuple[str, str]]:
    if start is not None or end is not None:
        shards_only = True
    if not shards_only:
        return sorted(entries.items())

    indexed: Dict[int, Tuple[str, str]] = {}
    for relative, digest in entries.items():
        match = SHARD_RE.fullmatch(relative)
        if match:
            indexed[int(match.group(1))] = (relative, digest)
    if not indexed:
        raise VerificationError("SHA256SUMS contains no shard entries")
    first = min(indexed) if start is None else start
    last = max(indexed) if end is None else end
    if first < 0 or last < 0 or first > last:
        raise VerificationError(f"invalid shard range: {first}..{last}")
    missing = [index for index in range(first, last + 1) if index not in indexed]
    if missing:
        raise VerificationError(f"requested shard is absent from SHA256SUMS: {missing[0]}")
    return [indexed[index] for index in range(first, last + 1)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path("."), help="local dataset root"
    )
    parser.add_argument(
        "--checksums",
        type=Path,
        help=f"checksum file (default: ROOT/{DEFAULT_CHECKSUMS})",
    )
    parser.add_argument("--shards-only", action="store_true", help="ignore metadata entries")
    parser.add_argument("--start-shard", type=int)
    parser.add_argument("--end-shard", type=int)
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also validate TAR names, exact NPZ/PNG/JSON triples, sidecars, sizes, and member hashes",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise VerificationError(f"dataset root is not a directory: {root}")
    checksum_path = args.checksums or (root / DEFAULT_CHECKSUMS)
    if not checksum_path.is_absolute():
        checksum_path = root / checksum_path
    entries = parse_sha256sums(checksum_path)
    selected = _select_entries(
        entries, args.shards_only, args.start_shard, args.end_shard
    )

    failures: List[str] = []
    verified_shards: List[Tuple[Path, str]] = []
    for position, (relative, expected) in enumerate(selected, 1):
        try:
            path = _local_file(root, relative)
            if not path.is_file():
                raise VerificationError("missing or non-regular file")
            actual = _sha256_file(path)
            if actual != expected:
                raise VerificationError(f"SHA256 mismatch (expected {expected}, got {actual})")
            if SHARD_RE.fullmatch(relative):
                verified_shards.append((path, relative))
            if not args.quiet:
                print(f"[{position}/{len(selected)}] OK {relative}")
        except (OSError, VerificationError) as exc:
            failures.append(f"{relative}: {exc}")
            print(f"FAIL {relative}: {exc}", file=sys.stderr)

    deep_samples = 0
    deep_members = 0
    if args.deep and not failures:
        seen: MutableSet[str] = set()
        for position, (path, relative) in enumerate(verified_shards, 1):
            samples, members = _deep_verify_tar(path, relative, seen)
            deep_samples += samples
            deep_members += members
            if not args.quiet:
                print(
                    f"[deep {position}/{len(verified_shards)}] OK {relative}: "
                    f"samples={samples}, members={members}"
                )

    if failures:
        raise VerificationError(f"verification failed for {len(failures)} file(s)")
    message = f"Verified {len(selected)} file(s) against SHA256SUMS"
    if args.deep:
        message += f"; deep-checked {deep_samples} samples / {deep_members} TAR members"
    print(message)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

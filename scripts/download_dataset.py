#!/usr/bin/env python3
"""Resumable, checksum-gated downloader for DeepTelecom UAV Dataset v1."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from typing import Dict, Iterable, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_REPO_ID = "KYGOYUAN/DeepTelecom_Partial"
DEFAULT_REVISION = "de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3"
CHECKSUM_PATH = "checksums/v1/SHA256SUMS"
SHARD_RE = re.compile(r"^data/v1/shards/shard-(\d{5})\.tar$")
SHA_RE = re.compile(r"^([0-9a-fA-F]{64})  ([^\r\n]+)$")
CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")
MAX_CHECKSUM_BYTES = 16 * 1024 * 1024
CHUNK_SIZE = 8 * 1024 * 1024


class DownloadError(RuntimeError):
    """A download cannot be completed without weakening an integrity rule."""


def _safe_repo_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise DownloadError(f"invalid Hugging Face repository id: {value!r}")
    return value


def _safe_remote_path(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise DownloadError(f"unsafe path in SHA256SUMS: {value!r}")
    parts = value.split("/")
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or any(part in ("", ".", "..") for part in parts)
        or candidate.as_posix() != value
    ):
        raise DownloadError(f"unsafe path in SHA256SUMS: {value!r}")
    return value


def parse_sha256sums(payload: bytes) -> Dict[str, str]:
    """Strictly parse GNU-style text without accepting path traversal."""
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DownloadError("SHA256SUMS is not valid UTF-8") from exc

    entries: Dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        match = SHA_RE.fullmatch(line)
        if match is None:
            raise DownloadError(f"malformed SHA256SUMS line {line_number}")
        digest, raw_path = match.groups()
        remote_path = _safe_remote_path(raw_path)
        if remote_path in entries:
            raise DownloadError(f"duplicate SHA256SUMS entry: {remote_path}")
        entries[remote_path] = digest.lower()
    if not entries:
        raise DownloadError("SHA256SUMS contains no entries")
    return entries


def _resolve_url(repo_id: str, revision: str, remote_path: str) -> str:
    encoded_repo = quote(_safe_repo_id(repo_id), safe="/")
    encoded_revision = quote(revision, safe="")
    encoded_path = quote(_safe_remote_path(remote_path), safe="/")
    return (
        f"https://huggingface.co/datasets/{encoded_repo}/resolve/"
        f"{encoded_revision}/{encoded_path}?download=true"
    )


def _headers() -> Dict[str, str]:
    headers = {
        "Accept-Encoding": "identity",
        "User-Agent": "deeptelecom-v1-downloader/1.0",
    }
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_small(url: str, retries: int, timeout: float) -> bytes:
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers=_headers())
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_CHECKSUM_BYTES + 1)
            if len(payload) > MAX_CHECKSUM_BYTES:
                raise DownloadError("remote SHA256SUMS exceeds the safety limit")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 30))
    raise DownloadError(f"failed to fetch {url}: {last_error}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_local_path(root: Path, remote_path: str) -> Path:
    relative = Path(*PurePosixPath(_safe_remote_path(remote_path)).parts)
    target = root / relative
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DownloadError(f"local path escapes output root: {remote_path}") from exc
    return target


def _ensure_regular_or_missing(path: Path, label: str) -> None:
    if path.is_symlink():
        raise DownloadError(f"refusing symlink at {label}: {path}")
    if path.exists() and not path.is_file():
        raise DownloadError(f"refusing non-regular {label}: {path}")


def _atomic_save_checksums(root: Path, payload: bytes) -> None:
    target = _safe_local_path(root, CHECKSUM_PATH)
    partial = target.with_name(target.name + ".partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_regular_or_missing(target, "checksum file")
    _ensure_regular_or_missing(partial, "checksum partial")

    if target.exists():
        if target.read_bytes() != payload:
            raise DownloadError(
                f"existing checksum file differs from the pinned remote revision: {target}"
            )
        return

    with partial.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if target.exists():
        raise DownloadError(f"destination appeared during checksum download: {target}")
    os.replace(partial, target)


def _partial_is_complete(partial: Path, expected_sha256: str) -> bool:
    return partial.exists() and _sha256(partial) == expected_sha256


def _download_one(
    url: str,
    target: Path,
    expected_sha256: str,
    retries: int,
    timeout: float,
) -> str:
    """Return ``downloaded`` or ``skipped``; never overwrite a bad final file."""
    partial = target.with_name(target.name + ".partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    _ensure_regular_or_missing(target, "destination")
    _ensure_regular_or_missing(partial, "partial download")

    if target.exists():
        actual = _sha256(target)
        if actual != expected_sha256:
            raise DownloadError(
                f"refusing to overwrite existing file with wrong SHA256: {target}\n"
                f"  expected {expected_sha256}\n  actual   {actual}"
            )
        return "skipped"

    last_error: Optional[BaseException] = None
    reset_partial = False
    for attempt in range(1, retries + 1):
        if reset_partial and partial.exists():
            with partial.open("wb"):
                pass
            reset_partial = False

        offset = partial.stat().st_size if partial.exists() else 0
        headers = _headers()
        if offset:
            headers["Range"] = f"bytes={offset}-"

        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                status = response.getcode()
                append = offset > 0 and status == 206
                if append:
                    content_range = response.headers.get("Content-Range", "")
                    match = CONTENT_RANGE_RE.fullmatch(content_range)
                    if match is None or int(match.group(1)) != offset:
                        raise DownloadError(
                            f"server returned an invalid Content-Range for {target.name}: "
                            f"{content_range!r}"
                        )
                elif offset and status == 200:
                    # The endpoint ignored Range; restarting the disposable partial is safe.
                    append = False
                elif status not in (200, 206):
                    raise DownloadError(f"unexpected HTTP status {status} for {target.name}")

                mode = "ab" if append else "wb"
                with partial.open(mode) as handle:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())

            actual = _sha256(partial)
            if actual != expected_sha256:
                last_error = DownloadError(
                    f"downloaded bytes have wrong SHA256 for {target.name}: {actual}"
                )
                reset_partial = True
            else:
                if target.exists():
                    raise DownloadError(f"destination appeared during download: {target}")
                os.replace(partial, target)
                return "downloaded"
        except HTTPError as exc:
            if exc.code == 416 and offset:
                if _partial_is_complete(partial, expected_sha256):
                    if target.exists():
                        raise DownloadError(f"destination appeared during download: {target}")
                    os.replace(partial, target)
                    return "downloaded"
                reset_partial = True
            last_error = exc
        except (URLError, TimeoutError, OSError, DownloadError) as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 30))

    raise DownloadError(f"failed to download {target.name} after {retries} attempts: {last_error}")


def _shard_entries(entries: Dict[str, str]) -> Dict[int, Tuple[str, str]]:
    shards: Dict[int, Tuple[str, str]] = {}
    for path, digest in entries.items():
        match = SHARD_RE.fullmatch(path)
        if match is None:
            continue
        index = int(match.group(1))
        if index in shards:
            raise DownloadError(f"duplicate shard index in SHA256SUMS: {index}")
        shards[index] = (path, digest)
    if not shards:
        raise DownloadError("remote SHA256SUMS contains no dataset shards")
    return shards


def _selected_indices(
    shards: Dict[int, Tuple[str, str]], start: Optional[int], end: Optional[int]
) -> Iterable[int]:
    first = min(shards) if start is None else start
    last = max(shards) if end is None else end
    if first < 0 or last < 0 or first > last:
        raise DownloadError(f"invalid shard range: {first}..{last}")
    missing = [index for index in range(first, last + 1) if index not in shards]
    if missing:
        preview = ", ".join(str(value) for value in missing[:10])
        raise DownloadError(f"requested shard indices are absent from SHA256SUMS: {preview}")
    return range(first, last + 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="HF dataset repository")
    parser.add_argument(
        "--revision",
        default=DEFAULT_REVISION,
        help="immutable HF revision (default: the DeepTelecom v1 release commit)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="dataset root; remote paths are preserved below it (default: current directory)",
    )
    parser.add_argument("--start-shard", "--start", dest="start_shard", type=int)
    parser.add_argument("--end-shard", "--end", dest="end_shard", type=int)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.retries < 1:
        raise DownloadError("--retries must be at least 1")
    if args.timeout <= 0:
        raise DownloadError("--timeout must be positive")
    if not args.revision or any(char.isspace() for char in args.revision):
        raise DownloadError("--revision must be non-empty and contain no whitespace")

    output_root = args.output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if not output_root.is_dir():
        raise DownloadError(f"output root is not a directory: {output_root}")

    checksum_url = _resolve_url(args.repo_id, args.revision, CHECKSUM_PATH)
    checksum_payload = _fetch_small(checksum_url, args.retries, args.timeout)
    entries = parse_sha256sums(checksum_payload)
    shards = _shard_entries(entries)
    indices = list(_selected_indices(shards, args.start_shard, args.end_shard))
    _atomic_save_checksums(output_root, checksum_payload)

    print(
        f"Pinned revision: {args.revision}\n"
        f"Downloading {len(indices)} shard(s) to {output_root}"
    )
    downloaded = 0
    skipped = 0
    for position, index in enumerate(indices, 1):
        remote_path, expected_sha256 = shards[index]
        target = _safe_local_path(output_root, remote_path)
        print(f"[{position}/{len(indices)}] {remote_path}", flush=True)
        result = _download_one(
            _resolve_url(args.repo_id, args.revision, remote_path),
            target,
            expected_sha256,
            args.retries,
            args.timeout,
        )
        downloaded += result == "downloaded"
        skipped += result == "skipped"
        print(f"  {result}: SHA256 {expected_sha256}")

    print(f"Complete: downloaded={downloaded}, verified_existing={skipped}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DownloadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

"""Deterministic, read-only subject fingerprinting for REFALL context generation."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .source_inventory import READ_CHUNK_BYTES, SKIP_DIRS

DEFAULT_TIMEOUT_SECONDS = 30
BINWALK_TIMEOUT_SECONDS = 120
SCAN_WORDS = ("executable", "firmware", "filesystem", "boot", "rom", "archive", "image", "data", "binary")
SCAN_SUFFIXES = {".bin", ".img", ".rom", ".fw", ".hex", ".elf", ".so", ".dylib", ".exe", ".zip", ".tar", ".gz", ".7z"}


def fingerprint_directory(
    root: Path | str,
    *,
    run_binwalk: bool = True,
    file_timeout: int = DEFAULT_TIMEOUT_SECONDS,
    binwalk_timeout: int = BINWALK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return a stable manifest and optional safe Binwalk results.

    All operations are read-only. Binwalk is invoked in signature-search mode;
    extraction, matryoshka recursion, and entropy analysis are deliberately not
    enabled.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"source root is not a directory: {root_path}")

    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root_path).as_posix()
            try:
                stat = path.stat()
                digest = _sha256(path)
            except OSError as exc:
                skipped.append({"path": rel, "reason": "unreadable", "detail": str(exc)})
                continue
            row: dict[str, Any] = {
                "path": rel,
                "size_bytes": stat.st_size,
                "mode": stat.st_mode & 0o7777,
                "sha256": digest,
            }
            if digest in seen:
                row["duplicate_of"] = seen[digest]["path"]
                row["file_type"] = seen[digest].get("file_type")
                row["scan_candidate"] = seen[digest].get("scan_candidate", False)
            else:
                row.update(_file_probe(path, timeout=file_timeout))
                seen[digest] = row
            files.append(row)

    duplicate_groups: dict[str, list[str]] = {}
    for row in files:
        duplicate_groups.setdefault(row["sha256"], []).append(row["path"])
    duplicate_groups = {digest: paths for digest, paths in duplicate_groups.items() if len(paths) > 1}

    binwalk = {"requested": bool(run_binwalk), "available": bool(shutil.which("binwalk")), "scanned": 0, "results": []}
    if run_binwalk:
        if not binwalk["available"]:
            binwalk["error"] = "binwalk executable not found"
        else:
            scanned_hashes: set[str] = set()
            for row in files:
                if not row.get("scan_candidate") or row["sha256"] in scanned_hashes:
                    continue
                scanned_hashes.add(row["sha256"])
                result = _binwalk_probe(root_path / row["path"], timeout=binwalk_timeout)
                row["binwalk"] = result
                binwalk["results"].append({"path": row["path"], "sha256": row["sha256"], **result})
                if result["status"] == "ok":
                    binwalk["scanned"] += 1

    manifest = {
        "schema": "refall.context-fingerprint.v1",
        "root": str(root_path),
        "files_total": len(files),
        "readable_files": len(files),
        "skipped": skipped,
        "deduplicated_files": len(seen),
        "duplicate_groups": list(duplicate_groups.values()),
        "files": files,
        "binwalk": binwalk,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical(_identity_manifest(manifest)).encode()
    ).hexdigest()
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _file_probe(path: Path, *, timeout: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(["file", "-b", str(path)], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"file_type": "unknown", "file_error": str(exc), "scan_candidate": True}
    file_type = (proc.stdout or "").strip() or "unknown"
    return {"file_type": file_type, "file_error": (proc.stderr or "").strip() or None, "scan_candidate": _needs_binwalk(path, file_type)}


def _needs_binwalk(path: Path, file_type: str) -> bool:
    lowered = file_type.lower()
    if path.suffix.lower() in SCAN_SUFFIXES:
        return True
    return any(word in lowered for word in SCAN_WORDS) and not any(
        ordinary in lowered for ordinary in ("text", "ascii", "unicode", "json", "xml", "pdf", "jpeg", "png", "gif")
    )


def _binwalk_probe(path: Path, *, timeout: int) -> dict[str, Any]:
    args = ["binwalk", "--search-all", str(path)]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "error": str(exc), "command": args}
    return {"status": "ok" if proc.returncode == 0 else "error", "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-20000:], "stderr": (proc.stderr or "")[-4000:], "command": args}


def _canonical(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _identity_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Exclude Binwalk's volatile elapsed time from the identity digest."""
    import copy

    stable = copy.deepcopy(manifest)
    rows = [item.get("binwalk") for item in stable.get("files", [])]
    rows.extend(stable.get("binwalk", {}).get("results", []))
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("stdout"), str):
            continue
        row["stdout"] = re.sub(
            r"(Analyzed .*? in )\d+(?:\.\d+)?( milliseconds)",
            r"\1<elapsed>\2",
            row["stdout"],
        )
    return stable

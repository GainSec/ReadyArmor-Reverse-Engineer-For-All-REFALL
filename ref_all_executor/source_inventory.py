from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


READ_CHUNK_BYTES = 1024 * 1024
SKIP_DIRS = {".git", ".refall", "refallsubloop", "__pycache__", "node_modules", ".venv"}
INCLUDE_DOT_DIRS = {".github", ".gitlab", ".circleci", ".azure", ".azuredevops", ".devcontainer"}
SOURCE_EXTENSIONS = {
    ".bash": "shell",
    ".c": "c",
    ".cfg": "config",
    ".conf": "config",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".h": "c-header",
    ".hpp": "cpp-header",
    ".hcl": "iac",
    ".html": "html",
    ".ini": "config",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".lua": "lua",
    ".md": "markdown",
    ".php": "php",
    ".pl": "perl",
    ".ps1": "powershell",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".tf": "iac",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}
SOURCE_NAMES = {
    ".dockerignore": "config",
    ".env": "config",
    ".gitignore": "config",
    ".npmrc": "config",
    ".pypirc": "config",
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "rakefile": "ruby",
    "gemfile": "ruby",
}


def build_source_inventory(subject: str, root: Path | str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"source root is not a directory: {root_path}")
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and (not name.startswith(".") or name in INCLUDE_DOT_DIRS)
        )
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            rel = _relative(root_path, path)
            if path.is_symlink():
                observations.append(_symlink_observation(root_path, path))
            try:
                stat = path.stat()
            except OSError as exc:
                skipped.append({"path": rel, "reason": "unreadable", "detail": str(exc)})
                continue
            try:
                facts = _file_facts(path)
            except OSError as exc:
                skipped.append({"path": rel, "reason": "unreadable", "detail": str(exc)})
                continue
            kind = _file_kind(path) or ("binary" if facts["binary"] else "unknown")
            files.append({
                "path": rel,
                "sha256": facts["sha256"],
                "size_bytes": stat.st_size,
                "total_lines": facts["total_lines"],
                "kind": kind,
                "src": "source-inventory",
            })
    inventory = {
        "subject": subject,
        "root": str(root_path),
        "files": files,
        "skipped": skipped,
        "observations": observations,
    }
    inventory["inventory_id"] = "inv_" + hashlib.sha256(
        json.dumps(
            {
                "subject": subject,
                "root": str(root_path),
                "files": [
                    {
                        "path": item["path"],
                        "sha256": item["sha256"],
                        "size_bytes": item["size_bytes"],
                        "total_lines": item["total_lines"],
                    }
                    for item in files
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return inventory


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _file_kind(path: Path) -> str:
    name = path.name.lower()
    if name.startswith(".env."):
        return "config"
    if name in SOURCE_NAMES:
        return SOURCE_NAMES[name]
    return SOURCE_EXTENSIONS.get(path.suffix.lower(), "")


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _file_facts(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    line_count = 0
    saw_data = False
    ends_with_newline = False
    binary = False
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            saw_data = True
            digest.update(chunk)
            line_count += chunk.count(b"\n")
            ends_with_newline = chunk.endswith(b"\n")
            if b"\x00" in chunk:
                binary = True
    if saw_data and not ends_with_newline:
        line_count += 1
    return {
        "sha256": digest.hexdigest(),
        "total_lines": max(1, line_count),
        "binary": binary,
    }


def _symlink_observation(root: Path, path: Path) -> dict[str, Any]:
    try:
        target = path.resolve()
        target.relative_to(root)
        off_root = False
    except (OSError, ValueError):
        target = path
        off_root = True
    return {
        "kind": "symlink",
        "path": _relative(root, path),
        "target": str(target),
        "off_root": off_root,
    }

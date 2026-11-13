"""Check staged files for private artifacts and common credential/path leaks."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PRIVATE_PARTS = {"var", "output", "materials", "private", "secrets", "node_modules",
                 ".playwright-cli", "android-player", "__pycache__"}
PRIVATE_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".pcm", ".mp4", ".mov", ".pdf",
                    ".docx", ".jsonl", ".log", ".key", ".pem", ".p12", ".pfx", ".sqlite", ".db"}
CONTENT_PATTERNS = (
    ("personal absolute path", re.compile(r"(?:/Users/|/home/)[A-Za-z0-9_.-]+/|[A-Z]:\\Users\\[^\\]+\\")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("provider token", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("literal credential", re.compile(r'''(?i)["']?(?:api[_-]?key|access[_-]?key|secret[_-]?key|password)["']?\s*[:=]\s*["']([A-Za-z0-9_+/=-]{24,})["']''')),
)


def inspect_blob(name: str, data: bytes) -> list[str]:
    path = Path(name)
    issues = []
    if (set(path.parts) & PRIVATE_PARTS or path.suffix.lower() in PRIVATE_SUFFIXES
            or path.name == "config.local.json" or any(part.startswith(".venv") for part in path.parts)
            or (path.name.startswith(".env") and path.name != ".env.example")):
        issues.append("private artifact")
    if b"\0" in data:
        issues.append("binary file needs explicit review")
        return issues
    text = data.decode("utf-8", errors="replace")
    for label, pattern in CONTENT_PATTERNS:
        if pattern.search(text):
            issues.append(label)
    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=root).split(b"\0")
    failed = False
    checked = 0
    for encoded in filter(None, names):
        name = encoded.decode()
        data = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        issues = inspect_blob(name, data)
        if issues:
            # Report only categories and file paths, never matched credentials.
            print(f"FAIL {name}: {', '.join(issues)}")
            failed = True
        checked += 1
    if not checked:
        print("No staged files. Stage the intended public source before checking.")
        return 1
    if not failed:
        print(f"PASS: checked {checked} staged files; no matching private artifacts or credential/path leaks.")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

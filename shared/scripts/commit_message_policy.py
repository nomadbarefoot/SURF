#!/usr/bin/env python3
"""Lightweight commit-message checks for local git hooks."""

from __future__ import annotations

import sys
from pathlib import Path


def check_file(message_path: str) -> int:
    """Validate a commit message file.

    Args:
        message_path: Path to the temporary commit message file.

    Returns:
        Process exit code (0 = ok, 1 = rejected).
    """
    message = Path(message_path).read_text(encoding="utf-8").strip()
    if not message:
        print("commit message is empty", file=sys.stderr)
        return 1

    for line in message.splitlines():
        lowered = line.lower()
        if "made-with" in lowered and "cursor" in lowered:
            print("commit message contains IDE promotional trailer", file=sys.stderr)
            return 1

    return 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "check-file":
        print("usage: commit_message_policy.py check-file <msg-file>", file=sys.stderr)
        return 2
    return check_file(sys.argv[2])


if __name__ == "__main__":
    raise SystemExit(main())

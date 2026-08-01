#!/usr/bin/env python3
"""PostToolUse hook: verify solution artifacts the moment they are written.

Exit 2 hands stderr back to Claude, so a broken artifact is reported to the
agent that just wrote it and gets fixed without a human stepping in.

Two rules that must not be relaxed:

1. This hook never edits files. A hook that rewrites what the agent just
   wrote races against the agent's own edits and produces bugs that are
   almost impossible to trace. It only reports.
2. Malformed JSON produces a human-readable message, never a traceback.

The fast path -- a write to anything we do not watch -- must stay cheap, so
the path test happens before any heavy import.
"""

from __future__ import annotations

import json
import sys

WATCHED_PREFIXES = ("solutions/", "configs/")
HOOK_MC_SPINS = 100_000


def _is_watched(path: str) -> bool:
    if not path.endswith(".json"):
        return False
    normalised = path.replace("\\", "/")
    return any(f"/{p}" in f"/{normalised}" for p in WATCHED_PREFIXES)


def main(stdin_text: str) -> tuple[int, str]:
    try:
        event = json.loads(stdin_text)
    except json.JSONDecodeError:
        return 0, ""

    path = (event.get("tool_input") or {}).get("file_path")
    if not path or not _is_watched(str(path)):
        return 0, ""

    from pathlib import Path

    target = Path(path)
    if not target.exists():
        return 0, ""

    # slotmath.cli._load_json has the equivalent guard; keep both in sync.
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return 2, f"{path}: cannot read ({exc.strerror})\n"
    except UnicodeDecodeError:
        return 2, f"{path}: not valid UTF-8 text\n"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return 2, f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}\n"

    from pydantic import ValidationError

    from slotmath.spec import GameSpec, load_spec
    from slotmath.verify import ReelConfig, verify

    # A GameSpec has "grid"; a ReelConfig has "reels".
    if "grid" in data and "reels" not in data:
        try:
            GameSpec.model_validate(data)
        except ValidationError as exc:
            return 2, f"{path}: invalid GameSpec\n{exc}\n"
        return 0, ""

    try:
        config = ReelConfig.model_validate(data)
    except ValidationError as exc:
        return 2, f"{path}: invalid ReelConfig\n{exc}\n"

    spec_path = Path(config.spec)
    if not spec_path.exists():
        return 2, f"{path}: referenced spec {config.spec} not found\n"

    report = verify(load_spec(spec_path), config, mc_spins=HOOK_MC_SPINS)
    if report.passed:
        return 0, ""
    return 2, f"{path} failed verification:\n{report.render()}\n"


if __name__ == "__main__":
    code, message = main(sys.stdin.read())
    if message:
        sys.stderr.write(message)
    raise SystemExit(code)

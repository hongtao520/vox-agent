#!/usr/bin/env python3
"""Load provider credentials from the skill-local, git-ignored .env file."""
from __future__ import annotations

import json
import os
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SKILL_DIR / ".env"


def _decode(value: str) -> str:
    value = value.strip()
    if value.startswith(('"', "'")):
        try:
            return str(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value[1:-1] if len(value) >= 2 and value[-1] == value[0] else value
    return value


def load_skill_env() -> Path:
    """Load simple KEY=VALUE entries without shell evaluation or logging secrets."""
    if not ENV_PATH.is_file():
        return ENV_PATH
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, _decode(value))
    return ENV_PATH

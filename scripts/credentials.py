#!/usr/bin/env python3
"""Load provider credentials from the skill-local, git-ignored .env file."""
from __future__ import annotations

import json
import os
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SKILL_DIR / ".env"

REQUIRED_CREDENTIALS = (
    ("LIBLIB_ACCESS_KEY", "Liblib AccessKey", "https://www.liblib.art/apis"),
    ("LIBLIB_SECRET_KEY", "Liblib SecretKey", "https://www.liblib.art/apis"),
    ("FISH_API_KEY", "Fish Audio API Key", "https://fish.audio/zh-CN/app/api-keys/"),
)


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


def missing_required_credentials() -> list[tuple[str, str, str]]:
    """Return missing Vox Agent credentials without ever exposing their values."""
    load_skill_env()
    return [item for item in REQUIRED_CREDENTIALS if not os.environ.get(item[0], "").strip()]


def require_setup() -> None:
    """Stop the first production stage with an actionable three-key setup guide."""
    missing = missing_required_credentials()
    if not missing:
        return
    names = ", ".join(item[0] for item in missing)
    raise SystemExit(
        "Vox Agent first-use setup is incomplete. Missing: " + names + "\n"
        "Create Liblib AccessKey + SecretKey at https://www.liblib.art/apis\n"
        "Create Fish Audio API Key at https://fish.audio/zh-CN/app/api-keys/\n"
        "Then run: python3 scripts/configure_credentials.py\n"
        "Enter secrets only in the hidden terminal prompts; never paste them into beats.json or commit them."
    )

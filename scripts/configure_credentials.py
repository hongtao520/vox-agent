#!/usr/bin/env python3
"""Securely collect the three credentials required by Vox Agent."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from credentials import ENV_PATH, REQUIRED_CREDENTIALS, load_skill_env


def status() -> bool:
    load_skill_env()
    missing = [name for name, _, _ in REQUIRED_CREDENTIALS if not os.environ.get(name, "").strip()]
    print(f"credential file: {ENV_PATH}")
    if missing:
        print("missing: " + ", ".join(missing))
        return False
    print("Codex chat image generation: no separate API key required")
    print("Liblib Kling image-to-video: configured")
    print("Fish Audio voice: configured")
    return True


def configure() -> None:
    print("Vox Agent needs exactly three credentials on first use.")
    print("1) Liblib AccessKey + SecretKey: https://www.liblib.art/apis")
    print("2) Fish Audio API Key: https://fish.audio/zh-CN/app/api-keys/")
    print("Credentials stay on this machine. Input is hidden and values are never printed.")
    values = {}
    for name, label, _ in REQUIRED_CREDENTIALS:
        value = getpass.getpass(f"{label}: ").strip()
        if not value:
            raise SystemExit(f"{label} is required; no file was written")
        values[name] = value
    lines = [
        "# Local provider credentials. Never commit this file.",
        "# Codex or Liblib handles keyframes; Liblib/Kling handles video; Fish handles narration.",
        *(f"{name}={json.dumps(value)}" for name, value in values.items()),
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    ENV_PATH.chmod(0o600)
    print(f"saved provider credentials to {ENV_PATH} (mode 0600)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report presence without showing values")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if status() else 1)
    configure()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Securely collect GPT Image 2, Liblib/Kling and Fish credentials."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from credentials import ENV_PATH, load_skill_env


OPTIONAL = (
    ("OPENAI_API_KEY", "OpenAI API Key (optional API-mode GPT Image 2)"),
)

REQUIRED = (
    ("LIBLIB_ACCESS_KEY", "Liblib AccessKey"),
    ("LIBLIB_SECRET_KEY", "Liblib SecretKey"),
    ("FISH_API_KEY", "Fish Audio API Key"),
)


def status() -> bool:
    load_skill_env()
    missing = [name for name, _ in REQUIRED if not os.environ.get(name, "").strip()]
    print(f"credential file: {ENV_PATH}")
    if missing:
        print("missing: " + ", ".join(missing))
        return False
    print("Codex GPT Image 2 keyframes: no API key required")
    print("OpenAI API-mode keyframes: " + ("configured" if os.environ.get("OPENAI_API_KEY", "").strip() else "not configured (optional)"))
    print("Liblib Kling image-to-video: configured")
    print("Fish Audio voice: configured")
    return True


def configure() -> None:
    print("Credentials stay on this machine. Input is hidden and values are never printed.")
    values = {}
    for name, label in REQUIRED:
        value = getpass.getpass(f"{label}: ").strip()
        if not value:
            raise SystemExit(f"{label} is required; no file was written")
        values[name] = value
    for name, label in OPTIONAL:
        value = getpass.getpass(f"{label}; press Enter to skip: ").strip()
        if value:
            values[name] = value
    lines = [
        "# Local provider credentials. Never commit this file.",
        "# OpenAI handles keyframes; Liblib/Kling handles image-to-video; Fish handles narration.",
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

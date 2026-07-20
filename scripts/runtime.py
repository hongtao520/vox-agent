#!/usr/bin/env python3
"""Resolve the default image route for Codex and non-Codex runtimes."""
from __future__ import annotations

import os
from typing import Optional


CODEX_MARKERS = (
    "CODEX_THREAD_ID",
    "CODEX_CI",
    "CODEX_SHELL",
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
)


def is_codex_environment() -> bool:
    """Return True when the script is running inside a Codex task environment."""
    override = os.environ.get("VOX_AGENT_RUNTIME", "").strip().lower()
    if override:
        if override not in {"codex", "external"}:
            raise SystemExit("VOX_AGENT_RUNTIME must be 'codex' or 'external'")
        return override == "codex"
    return any(os.environ.get(name, "").strip() for name in CODEX_MARKERS)


def resolve_image_provider(requested: Optional[str]) -> str:
    """Use Codex chat images in Codex; otherwise keep the whole batch on Liblib."""
    requested = (requested or "auto").strip().lower()
    if requested == "openai":
        return "openai"  # legacy explicit unattended API mode
    if requested not in {"auto", "codex", "liblib", "liblibtv"}:
        raise SystemExit("image_provider must be auto, codex, liblib, or openai")
    if requested in {"liblib", "liblibtv"}:
        return "liblib"
    return "codex" if is_codex_environment() else "liblib"

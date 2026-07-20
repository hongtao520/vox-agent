#!/usr/bin/env python3
"""Generate missing B-roll keyframes with Liblib after one Codex failure.

Codex image generation is an agent-owned tool call, so a local Python process
cannot catch its network exception.  The workflow therefore uses an explicit
per-shot circuit breaker:

1. Call Codex image generation once for a manifest item.
2. If that call fails, run this script for that key.  Do not retry Codex.

Usage:
  python3 scripts/keyframe_fallback.py out/project --only 2a
  python3 scripts/keyframe_fallback.py out/project          # every missing item
"""
from __future__ import annotations

import argparse
import json
import os

from openai_image import normalize_aspect
from provider import get_provider, run_jobs
from styles import compose_collage_prompt, compose_keyframe_prompt, resolve_theme


def shots_of(beat):
    if beat.get("shots"):
        for shot in beat["shots"]:
            yield shot, f"{beat['id']}{shot.get('id', '')}"
    else:
        yield beat, str(beat["id"])


def build_prompt(doc, beat, shot):
    existing = shot.get("keyframe_prompt")
    if existing:
        return existing
    aspect = doc.get("aspect", "16:9")
    if doc.get("style", "collage") != "collage":
        return compose_keyframe_prompt(
            doc.get("era"), shot["scene"], beat.get("title_cn", ""),
            beat.get("title_en", ""), aspect,
        )
    theme = resolve_theme(doc.get("theme")) or {}
    return compose_collage_prompt(
        shot["scene"], beat.get("title_cn", ""), beat.get("title_en", ""),
        beat.get("bg", "warm ochre"), aspect,
        with_title=shot.get("title", True),
        style=theme.get("idiom") or doc.get("collage_style", "american-retro"),
        palette=theme.get("palette") or doc.get("palette"),
        type_style=theme.get("type_style") or doc.get("type_style"),
        finish=theme.get("finish") or doc.get("finish"),
    )


def run(project_dir, only=None):
    beats_path = os.path.join(project_dir, "beats.json")
    with open(beats_path, encoding="utf-8") as source:
        doc = json.load(source)

    provider_name = doc.get("image_fallback_provider", "liblib")
    if str(provider_name).lower() not in {"liblib", "liblibtv"}:
        raise SystemExit("image_fallback_provider must be 'liblib'")
    config = (doc.get("image_fallback_provider_config")
              or doc.get("video_provider_config") or {})
    provider = get_provider(provider_name, config)
    model = doc.get("image_fallback_model", "liblib-ultra")
    aspect = doc.get("aspect", "16:9")
    keyframe_dir = os.path.join(project_dir, "keyframes")
    os.makedirs(keyframe_dir, exist_ok=True)

    specs, metadata = {}, {}
    for beat in doc["beats"]:
        for shot, key in shots_of(beat):
            if only and key not in only:
                continue
            existing = shot.get("keyframe_path")
            existing = (existing if not existing or os.path.isabs(existing)
                        else os.path.join(project_dir, existing))
            if shot.get("keyframe_url") or (existing and os.path.isfile(existing)):
                print(f"[{key}] already has a keyframe; skipped")
                continue
            destination = os.path.abspath(os.path.join(keyframe_dir, f"kf_{key}.png"))
            # A provider download may have completed before a local post-process
            # failure (for example, a missing Pillow install).  Resume from that
            # file instead of submitting and charging for the same image again.
            if os.path.isfile(destination):
                normalize_aspect(destination, aspect)
                shot["keyframe_path"] = destination
                shot["keyframe_source"] = {
                    "provider": "liblib",
                    "model": model,
                    "reason": "codex_failed_once",
                    "recovered_download": True,
                }
                shot["codex_generation_failed"] = True
                print(f"[{key}] recovered downloaded Liblib fallback {destination}")
                continue
            prompt = build_prompt(doc, beat, shot)
            shot["keyframe_prompt"] = prompt
            specs[key] = (
                lambda p=prompt: provider.submit_image(
                    model, p, aspect_ratio=aspect,
                    steps=int(config.get("image_steps", 30)),
                )
            )
            metadata[key] = shot
            print(f"[{key}] Codex circuit open -> queued on Liblib image fallback")

    if not specs:
        print("no missing keyframes selected")
        with open(beats_path, "w", encoding="utf-8") as target:
            json.dump(doc, target, ensure_ascii=False, indent=2)
        print("updated", beats_path)
        return

    outputs = run_jobs(
        provider, specs,
        poll_s=int(config.get("image_poll_s", 5)),
        stall_s=int(config.get("image_stall_s", 240)),
        max_retries=int(config.get("image_max_retries", 1)),
        deadline_s=int(config.get("image_deadline_s", 900)),
    )
    failed = []
    for key, url in outputs.items():
        if not url:
            failed.append(key)
            continue
        destination = os.path.abspath(os.path.join(keyframe_dir, f"kf_{key}.png"))
        provider.download(url, destination)
        normalize_aspect(destination, aspect)
        shot = metadata[key]
        shot["keyframe_path"] = destination
        shot["keyframe_url"] = url
        shot["keyframe_source"] = {
            "provider": "liblib",
            "model": model,
            "reason": "codex_failed_once",
        }
        shot["codex_generation_failed"] = True
        print(f"[{key}] Liblib fallback saved {destination}")

    with open(beats_path, "w", encoding="utf-8") as target:
        json.dump(doc, target, ensure_ascii=False, indent=2)
    if failed:
        raise SystemExit("Liblib fallback failed for: " + ", ".join(failed))
    print("updated", beats_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="comma-separated shot keys, for example 2a,3b")
    args = parser.parse_args()
    only = set(filter(None, (args.only or "").split(","))) or None
    run(os.path.abspath(args.project_dir), only)


if __name__ == "__main__":
    main()

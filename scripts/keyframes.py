#!/usr/bin/env python3
"""
Keyframe stage: one styled keyframe per SHOT.

Each beat holds one or more shots (different framings of the same narration
beat) so the cut has variety. Codex mode writes a GPT Image 2 manifest; API
mode writes local PNG files directly.

Usage: python3 keyframes.py <project_dir>   (default: out/tang-30s)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai_image import OpenAIImageClient, normalize_aspect
from styles import compose_keyframe_prompt, compose_collage_prompt, resolve_theme

IMAGE_MODEL = "gpt-image-2"


def shots_of(beat):
    """Yield (shot_dict, shot_key) for a beat; synthesize one shot if none."""
    if beat.get("shots"):
        for s in beat["shots"]:
            yield s, f"{beat['id']}{s.get('id','')}"
    else:
        yield beat, f"{beat['id']}"   # beat acts as its own single shot


def run(project_dir):
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath) as f:
        doc = json.load(f)
    aspect = doc.get("aspect", "16:9")
    image_provider = str(doc.get("image_provider", "codex")).lower()
    if image_provider not in {"codex", "openai"}:
        raise SystemExit("image_provider must be 'codex' or 'openai'; Liblib keyframe generation has been removed")
    img_model = doc.get("image_model", IMAGE_MODEL)
    if not str(img_model).startswith("gpt-image-2"):
        raise SystemExit("image_model must be gpt-image-2 (or a gpt-image-2 snapshot)")
    image_config = doc.get("image_provider_config") or {}
    quality = image_config.get("quality", doc.get("image_quality", "medium"))
    style = doc.get("style", "painterly")
    theme = resolve_theme(doc.get("theme")) or {}   # theme preset -> full look bundle
    collage_style = theme.get("idiom") or doc.get("collage_style", "american-retro")
    # a registered theme wins; a custom (unregistered) theme may set these at doc level
    t_palette = theme.get("palette") or doc.get("palette")
    t_type = theme.get("type_style") or doc.get("type_style")
    t_finish = theme.get("finish") or doc.get("finish")
    era = doc.get("era")            # only needed for the painterly (per-dynasty) style
    kf_dir = os.path.join(project_dir, "keyframes")
    os.makedirs(kf_dir, exist_ok=True)

    jobs, by_key = {}, {}
    for beat in doc["beats"]:
        for shot, key in shots_of(beat):
            existing = shot.get("keyframe_path")
            existing_path = (existing if not existing or os.path.isabs(existing)
                             else os.path.join(project_dir, existing))
            if shot.get("keyframe_url") or (existing_path and os.path.exists(existing_path)):
                continue
            scene = shot["scene"]
            if style == "collage":
                prompt = compose_collage_prompt(scene, beat["title_cn"], beat["title_en"],
                                                beat.get("bg", "warm ochre"), aspect,
                                                with_title=shot.get("title", True),
                                                style=collage_style, palette=t_palette,
                                                type_style=t_type, finish=t_finish)
            else:
                prompt = compose_keyframe_prompt(era, scene, beat["title_cn"],
                                                 beat["title_en"], aspect)
            shot["keyframe_prompt"] = prompt
            dest = os.path.join(kf_dir, f"kf_{key}.png")
            if os.path.exists(dest):
                normalize_aspect(dest, aspect)
                shot["keyframe_path"] = os.path.abspath(dest)
                shot["keyframe_source"] = {"provider": image_provider, "model": img_model}
                print(f"[{key}] registered existing {dest}")
                continue
            jobs[key] = (prompt, dest)
            by_key[key] = shot

    if image_provider == "codex":
        manifest_path = os.path.join(kf_dir, "gpt-image-2-manifest.json")
        manifest = {
            "model": img_model,
            "aspect": aspect,
            "instruction": "Use Codex image generation for every item and save the PNG at dest, then rerun keyframes.py to register it.",
            "items": [
                {"key": key, "prompt": prompt, "dest": os.path.abspath(dest)}
                for key, (prompt, dest) in jobs.items()
            ],
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"Codex GPT Image 2 manifest -> {manifest_path}")
        if jobs:
            print("Generate every manifest item with Codex image generation, save it at dest, then rerun this command.")
    else:
        client = OpenAIImageClient(image_config)
        workers = max(1, int(image_config.get("max_concurrency", 2)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(client.generate, prompt, dest, model=img_model, aspect=aspect,
                            quality=quality, output_format="png"): key
                for key, (prompt, dest) in jobs.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                dest = future.result()
                shot = by_key[key]
                shot["keyframe_path"] = dest
                shot["keyframe_source"] = {"provider": "openai", "model": img_model}
                shot.pop("keyframe_url", None)
                print(f"[{key}] GPT Image 2 saved {dest}")

    with open(bpath, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("updated", bpath)


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "out", "tang-30s")
    run(os.path.abspath(proj))

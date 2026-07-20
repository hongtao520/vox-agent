#!/usr/bin/env python3
"""
Style bake-off: render ONE representative beat in several candidate collage styles so
the user can pick the visual idiom before committing the whole film.

Hybrid selection: Claude reads the topic and chooses which idioms to try (names from
styles.STYLE_LIBRARY, or a custom idiom string), matching the topic's era/culture/tone —
don't default to Chinese motifs for a Western topic. Then the human picks by eye.

Usage:
  python3 style_bakeoff.py <project_dir> [style1,style2,...] [beat_index]
Defaults: the 4 Western library styles, beat 0. Output -> <project>/style-bakeoff/<style>.png
In Codex mode, generate the manifest items first. Then set "collage_style": "<pick>".
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from credentials import require_setup
from openai_image import OpenAIImageClient
from provider import get_provider, run_jobs
from runtime import resolve_image_provider
from styles import compose_collage_prompt, STYLE_LIBRARY, THEME_PRESETS, resolve_theme

IMAGE_MODEL = "gpt-image-2"
# candidates are THEME names (full look bundles); Claude picks topic-fitting ones
DEFAULT_CANDIDATES = ["american-retro", "swiss-modern", "punk-zine", "atomic-age"]


def first_shot(beat):
    return beat["shots"][0] if beat.get("shots") else beat


def run(project_dir, styles=None, beat_index=0):
    require_setup()
    styles = styles or DEFAULT_CANDIDATES
    with open(os.path.join(project_dir, "beats.json")) as f:
        doc = json.load(f)
    aspect = doc.get("aspect", "16:9")
    image_provider = resolve_image_provider(str(doc.get("image_provider", "auto")))
    img_model = doc.get("image_model", IMAGE_MODEL)
    if not str(img_model).startswith("gpt-image-2"):
        raise SystemExit("image_model must be gpt-image-2 (or a gpt-image-2 snapshot)")
    image_config = doc.get("image_provider_config") or {}
    quality = image_config.get("quality", doc.get("image_quality", "medium"))
    beat = doc["beats"][beat_index]
    shot = first_shot(beat)
    scene, bg = shot["scene"], beat.get("bg", "warm ochre")
    tcn, ten = beat.get("title_cn", ""), beat.get("title_en", "")
    out = os.path.join(project_dir, "style-bakeoff"); os.makedirs(out, exist_ok=True)

    specs = {}
    for name in styles:
        tp = resolve_theme(name) or {}              # theme name -> full look bundle
        prompt = compose_collage_prompt(scene, tcn, ten, bg, aspect,
                                        style=tp.get("idiom", name), palette=tp.get("palette"),
                                        type_style=tp.get("type_style"), finish=tp.get("finish"))
        specs[name] = (prompt, os.path.join(out, f"{name}.png"))
        tag = "library" if name in STYLE_LIBRARY else "custom"
        print(f"[{name}] ({tag}) queued")

    if image_provider == "codex":
        manifest = {
            "model": img_model,
            "aspect": aspect,
            "instruction": "Use Codex image generation for every item and save the PNG at dest.",
            "items": [
                {"key": name, "prompt": prompt, "dest": os.path.abspath(dest)}
                for name, (prompt, dest) in specs.items()
            ],
        }
        manifest_path = os.path.join(out, "gpt-image-2-manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"Codex GPT Image 2 manifest -> {manifest_path}")
    elif image_provider == "openai":
        client = OpenAIImageClient(image_config)
        workers = max(1, int(image_config.get("max_concurrency", 2)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(client.generate, prompt, dest, model=img_model, aspect=aspect,
                            quality=quality, output_format="png"): name
                for name, (prompt, dest) in specs.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                print(f"[{name}] saved {future.result()}")
    else:
        config = (doc.get("image_fallback_provider_config")
                  or doc.get("video_provider_config") or {})
        provider = get_provider("liblib", config)
        model = doc.get("image_fallback_model", "liblib-ultra")
        jobs = {
            name: (lambda p=prompt: provider.submit_image(
                model, p, aspect_ratio=aspect,
                steps=int(config.get("image_steps", 30)),
            ))
            for name, (prompt, _) in specs.items()
        }
        outputs = run_jobs(
            provider, jobs,
            poll_s=int(config.get("image_poll_s", 5)),
            stall_s=int(config.get("image_stall_s", 240)),
            max_retries=int(config.get("image_max_retries", 1)),
            deadline_s=int(config.get("image_deadline_s", 900)),
        )
        failed = []
        for name, url in outputs.items():
            if not url:
                failed.append(name)
                continue
            destination = os.path.abspath(specs[name][1])
            provider.download(url, destination)
            print(f"[{name}] Liblib candidate saved {destination}")
        if failed:
            raise SystemExit("Liblib style bake-off failed for: " + ", ".join(failed))
    print(f"\nsaved candidates to {out} — review, then set \"collage_style\" in beats.json.")


if __name__ == "__main__":
    proj = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                           os.path.join(os.path.dirname(__file__), "..", "out", "money-60s"))
    styles = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    bi = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    run(proj, styles, bi)

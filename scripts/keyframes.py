#!/usr/bin/env python3
"""
Keyframe stage: one styled keyframe per SHOT.

Each beat holds one or more shots (different framings of the same narration
beat) so the cut has variety. In Codex, auto mode writes a GPT Image 2
manifest. Outside Codex, auto mode generates the entire batch through Liblib.

Usage: python3 keyframes.py <project_dir>   (default: out/tang-30s)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from codex_parallel import execution_contract, instruction as parallel_instruction
from credentials import require_setup
from openai_image import OpenAIImageClient, normalize_aspect
from provider import get_provider, run_jobs
from runtime import resolve_image_provider
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
    require_setup()
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath) as f:
        doc = json.load(f)
    aspect = doc.get("aspect", "16:9")
    requested_provider = str(doc.get("image_provider", "auto")).lower()
    image_provider = resolve_image_provider(requested_provider)
    doc["resolved_image_provider"] = image_provider
    print(f"image route: requested={requested_provider}, resolved={image_provider}")
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
            source_provider = (shot.get("keyframe_source") or {}).get("provider")
            provider_mismatch = image_provider == "liblib" and source_provider != "liblib"
            existing = shot.get("keyframe_path")
            existing_path = (existing if not existing or os.path.isabs(existing)
                             else os.path.join(project_dir, existing))
            if not provider_mismatch and (
                shot.get("keyframe_url") or (existing_path and os.path.exists(existing_path))
            ):
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
            suffix = "_liblib" if image_provider == "liblib" else ""
            dest = os.path.join(kf_dir, f"kf_{key}{suffix}.png")
            if os.path.exists(dest):
                normalize_aspect(dest, aspect)
                shot["keyframe_path"] = os.path.abspath(dest)
                source_model = (doc.get("image_fallback_model", "liblib-ultra")
                                if image_provider == "liblib" else img_model)
                shot["keyframe_source"] = {"provider": image_provider, "model": source_model}
                print(f"[{key}] registered existing {dest}")
                continue
            jobs[key] = (prompt, dest)
            by_key[key] = shot

    if image_provider == "codex":
        manifest_path = os.path.join(kf_dir, "gpt-image-2-manifest.json")
        items = [
            {"key": key, "prompt": prompt, "dest": os.path.abspath(dest)}
            for key, (prompt, dest) in jobs.items()
        ]
        manifest = {
            "model": img_model,
            "aspect": aspect,
            "instruction": parallel_instruction(
                len(items), producer="keyframes.py", edit=False,
            ),
            "execution": execution_contract(len(items), edit=False),
            "items": items,
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"Codex GPT Image 2 manifest -> {manifest_path}")
        if jobs:
            print(
                f"Spawn {len(items)} logical image subagents for {len(items)} manifest items "
                "(one image per agent), then rerun this command after all succeed."
            )
    elif image_provider == "openai":
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
    else:
        config = (doc.get("image_fallback_provider_config")
                  or doc.get("video_provider_config") or {})
        provider = get_provider("liblib", config)
        model = doc.get("image_fallback_model", "liblib-ultra")
        specs = {
            key: (lambda p=prompt: provider.submit_image(
                model, p, aspect_ratio=aspect,
                steps=int(config.get("image_steps", 30)),
            ))
            for key, (prompt, _) in jobs.items()
        }
        outputs = run_jobs(
            provider, specs,
            poll_s=int(config.get("image_poll_s", 5)),
            stall_s=int(config.get("image_stall_s", 240)),
            max_retries=int(config.get("image_max_retries", 1)),
            deadline_s=int(config.get("image_deadline_s", 900)),
        ) if specs else {}
        failed = []
        for key, url in outputs.items():
            if not url:
                failed.append(key)
                continue
            destination = os.path.abspath(jobs[key][1])
            provider.download(url, destination)
            normalize_aspect(destination, aspect)
            shot = by_key[key]
            shot["keyframe_path"] = destination
            shot["keyframe_url"] = url
            shot["keyframe_source"] = {"provider": "liblib", "model": model,
                                       "reason": "non_codex_batch"}
            print(f"[{key}] Liblib keyframe saved {destination}")
        if failed:
            raise SystemExit("Liblib keyframe generation failed for: " + ", ".join(failed))

    if not jobs or image_provider != "codex":
        sources = {
            (shot.get("keyframe_source") or {}).get("provider")
            for beat in doc["beats"] for shot, _ in shots_of(beat)
        }
        if len(sources) == 1 and None not in sources:
            doc["keyframe_batch_provider"] = next(iter(sources))

    with open(bpath, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("updated", bpath)


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "out", "tang-30s")
    run(os.path.abspath(proj))

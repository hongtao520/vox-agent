#!/usr/bin/env python3
"""
C-roll keyframe stage: anchor ONE still photo (a person or a product shot)
inside generated collage posters — "cutout roll".

Where A-roll re-styles a talking-head VIDEO (performance preserved) and B-roll
generates posters from TEXT alone, C-roll takes a single PHOTO: the subject is
cut out as a PHOTOGRAPHIC sticker (never redrawn) and the collage world is
generated around it per beat, via an image-EDIT model. The posters then animate
through the normal clips.py stage — this script also writes an `anchor_freeze`
guard into beats.json so the motion prompts keep the subject frozen.

Validated 2026-07-17 on two real productions (a product bottle; a portrait →
paper-doll explainer). Three hard-won prompt rules are baked in below:
  1. Poses/expressions must be expressed by the BODY only — asking the model
     to change the face (a wink, a smile) makes it redraw the face.
  2. Halftone/print texture bleeds onto the face unless you explicitly scope
     it to the background.
  3. For portraits, clothing must be locked too, or the paper-doll body drifts.
And one from the product run: label typography survives the edit but can be
re-lettered by the VIDEO stage — hence the LABEL/FACE FREEZE line that this
script hands to clips.py.

beats.json additions (see SKILL.md "C-roll mode"):
  "mode": "croll",
  "anchor_photo": "path/to/photo.png",       # local path or URL
  "croll_subject": "portrait" | "product",
  "subject_wardrobe": "her cream knitted sweater and charcoal trousers",  # portrait only
  "subject_desc": "the perfume bottle",       # product only (short noun phrase)

Usage: python3 croll_keyframes.py <project_dir>
"""
import json
import os
import sys

from codex_parallel import execution_contract, instruction as parallel_instruction
from credentials import require_setup
from openai_image import normalize_aspect
from runtime import resolve_image_provider
from styles import compose_collage_prompt, resolve_theme

EDIT_MODEL = "gpt-image-2"

FACE_LOCK = (
    "The person's face and hair from the attached photo are cut out as a PHOTOGRAPHIC "
    "sticker with a torn white paper border — keep the facial identity, features and the "
    "exact expression from the photo pixel-faithful; do not redraw, repaint or stylize the "
    "face; NO halftone dots, print texture or ink treatment on the face or hair — the face "
    "stays a clean photographic print. All poses and gestures are expressed by the body "
    "only. From the neck down the body is a hand-drawn paper-doll illustration jointed "
    "like a vintage paper puppet with visible cut edges, FULLY CLOTHED in {wardrobe}. "
)

PRODUCT_LOCK = (
    "{subject} from the attached photo is cut out as a PHOTOGRAPHIC sticker with a clean "
    "scissor-cut edge and a soft real paper drop shadow — keep its exact shape, materials, "
    "surface reflections and every word of its label typography pixel-faithful. Do not "
    "redraw, restyle or repaint the subject or its label. Re-style ONLY the world around "
    "it as printed paper collage. "
)

# Appended to every C-roll poster prompt. Rules 2+3 from the validated runs.
CROLL_GUARDS = (
    " Halftone dots and print textures live on the BACKGROUND only. Newspaper scraps carry "
    "completely UNREADABLE blurred micro-text. No readable text anywhere in the image."
)

# Written into beats.json for clips.py to inject into every motion prompt.
FREEZE = {
    "portrait": ("FREEZE the photographic face sticker — it is a frozen layer, "
                 "pixel-identical to the still for the entire duration; never redraw, warp "
                 "or animate the face; the paper-doll body may shift slightly at its joints."),
    "product": ("FREEZE the photographic subject sticker and its label — a frozen layer, "
                "pixel-identical to the still for the entire duration; every letter of the "
                "label stays exactly as in the still; it may only settle gently with its "
                "drop shadow."),
}


def build_lock(doc):
    kind = doc.get("croll_subject", "portrait")
    if kind == "product":
        return PRODUCT_LOCK.format(subject=doc.get("subject_desc", "The product")), kind
    wardrobe = doc.get("subject_wardrobe", "the same outfit as in the photo")
    return FACE_LOCK.format(wardrobe=wardrobe), kind


def shots_of(beat):
    if beat.get("shots"):
        for s in beat["shots"]:
            yield s, f"{beat['id']}{s.get('id','')}"
    else:
        yield beat, f"{beat['id']}"


def run(project_dir):
    require_setup()
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath) as f:
        doc = json.load(f)
    photo = doc["anchor_photo"]
    aspect = doc.get("aspect", "9:16")
    image_provider = resolve_image_provider(str(doc.get("image_provider", "auto")))
    if image_provider != "codex":
        raise SystemExit(
            "C-roll anchor-preserving image editing currently requires a Codex environment. "
            "Liblib text-to-image can handle B-roll batches but cannot preserve the supplied "
            "anchor without a custom reference-image workflow."
        )
    img_model = doc.get("image_model", EDIT_MODEL)
    if not str(img_model).startswith("gpt-image-2"):
        raise SystemExit("image_model must be gpt-image-2 (or a gpt-image-2 snapshot)")
    theme = resolve_theme(doc.get("theme")) or {}
    collage_style = theme.get("idiom") or doc.get("collage_style", "newsprint-editorial")
    lock, kind = build_lock(doc)
    kf_dir = os.path.join(project_dir, "keyframes")
    os.makedirs(kf_dir, exist_ok=True)

    if str(photo).startswith(("http://", "https://")):
        raise SystemExit("Codex GPT Image 2 editing needs anchor_photo as a local file path")
    photo = os.path.expanduser(photo)
    photo = os.path.abspath(photo if os.path.isabs(photo) else os.path.join(project_dir, photo))
    if not os.path.isfile(photo):
        raise SystemExit(f"anchor_photo does not exist: {photo}")
    doc["anchor_freeze"] = FREEZE[kind]

    items = []
    for beat in doc["beats"]:
        for shot, key in shots_of(beat):
            dest = os.path.abspath(os.path.join(kf_dir, f"kf_{key}.png"))
            existing = shot.get("keyframe_path")
            existing_path = (existing if not existing or os.path.isabs(existing)
                             else os.path.join(project_dir, existing))
            if shot.get("keyframe_url") or (existing_path and os.path.exists(existing_path)):
                continue
            if os.path.exists(dest):
                normalize_aspect(dest, aspect)
                shot["keyframe_path"] = dest
                shot["keyframe_source"] = {"provider": "codex", "model": img_model, "mode": "edit"}
                continue
            world = compose_collage_prompt(shot["scene"], "", "",
                                           beat.get("bg", "flat cream paper"), aspect,
                                           with_title=False, style=collage_style,
                                           palette=theme.get("palette") or doc.get("palette"),
                                           type_style=theme.get("type_style") or doc.get("type_style"),
                                           finish=theme.get("finish") or doc.get("finish"))
            prompt = lock + world + CROLL_GUARDS
            shot["keyframe_prompt"] = prompt
            items.append({"key": key, "prompt": prompt, "dest": dest,
                          "reference_images": [photo]})

    manifest_path = os.path.join(kf_dir, "gpt-image-2-edit-manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({
            "model": img_model,
            "aspect": aspect,
            "instruction": parallel_instruction(
                len(items), producer="croll_keyframes.py", edit=True,
            ),
            "execution": execution_contract(len(items), edit=True),
            "items": items,
        }, f, ensure_ascii=False, indent=2)
    print(f"Codex GPT Image 2 edit manifest -> {manifest_path}")
    if items:
        print(f"Spawn {len(items)} logical image-edit subagents (one per keyframe).")

    with open(bpath, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("updated", bpath)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python3 croll_keyframes.py <project_dir>")
    run(os.path.abspath(sys.argv[1]))

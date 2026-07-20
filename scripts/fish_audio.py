#!/usr/bin/env python3
"""Fish Audio TTS helpers for Vox Agent.

Credentials are read only from FISH_API_KEY.  They are never written to
beats.json or included in logs.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

from credentials import load_skill_env


load_skill_env()


API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_VOICE_NAME = "历史故事·清晰"
DEFAULT_REFERENCE_ID = "6fc59d2b56cf402eb572934114c8d8aa"
AUDITION_TEXT = "秦统一天下后，先要解决的，是七国的钱不能通用。"
AUDITION_VOICES = [
    ("01_纪录片男声_沉稳", "7d4cc998f68c413ba5605d892d7acc87"),
    ("02_纪录片男声_年长", "f51dfe8db3524c89a4201aacfa18e56e"),
    ("03_历史故事_清晰", "6fc59d2b56cf402eb572934114c8d8aa"),
    ("04_温暖磁性旁白", "4d0e64e39e4b4f31a816f133795c0db5"),
    ("05_叙事旁白_戏剧感", "6910bc3ba4284e31b49be252faf3601b"),
    ("06_宣传片男声_浑厚", "36ef842120654ee6b38ef43c8f08535a"),
]


def _key() -> str:
    key = os.environ.get("FISH_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "FISH_API_KEY is not set. Create a key at "
            "https://fish.audio/app/api-keys and export it before retrying."
        )
    return key


def synthesize(
    text: str,
    reference_id: str,
    output: os.PathLike[str] | str,
    *,
    model: str = DEFAULT_MODEL,
    speed: float = 1.0,
    temperature: float = 0.65,
    top_p: float = 0.7,
) -> pathlib.Path:
    output = pathlib.Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "text": text,
            "reference_id": reference_id,
            "format": "wav",
            # Fish WAV currently accepts up to 44.1 kHz. Assembly normalizes to 48 kHz.
            "sample_rate": 44100,
            "normalize": True,
            "latency": "normal",
            "temperature": temperature,
            "top_p": top_p,
            "prosody": {"speed": speed, "volume": 0},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/v1/tts",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {_key()}",
            "Content-Type": "application/json",
            "model": model,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"Fish Audio TTS failed ({exc.code}): {detail}") from exc
    if not audio:
        raise SystemExit("Fish Audio returned an empty audio response")
    output.write_bytes(audio)
    return output.resolve()


def generate_auditions(output_dir: str, text: str = AUDITION_TEXT) -> list[pathlib.Path]:
    output = pathlib.Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for name, reference_id in AUDITION_VOICES:
        path = synthesize(text, reference_id, output / f"{name}.wav")
        results.append(path)
        print(f"generated {path.name}")
    manifest = {
        "provider": "fish",
        "model": DEFAULT_MODEL,
        "text": text,
        "voices": [
            {"order": i, "name": name, "reference_id": reference_id, "file": f"{name}.wav"}
            for i, (name, reference_id) in enumerate(AUDITION_VOICES, 1)
        ],
    }
    (output / "试听清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def generate_project(project_dir: str) -> None:
    project = pathlib.Path(project_dir).resolve()
    beats_path = project / "beats.json"
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    voice = doc.get("voice") or {}
    if not voice:
        voice = {
            "provider": "fish", "model": DEFAULT_MODEL,
            "name": DEFAULT_VOICE_NAME, "reference_id": DEFAULT_REFERENCE_ID,
            "speed": 1.0, "temperature": 0.65, "top_p": 0.7,
            "trim_silence": True,
        }
        doc["voice"] = voice
    if voice.get("provider") != "fish":
        raise SystemExit('Set voice.provider to "fish" in beats.json')
    reference_id = voice.get("reference_id") or DEFAULT_REFERENCE_ID
    voice.setdefault("reference_id", reference_id)
    voice.setdefault("name", DEFAULT_VOICE_NAME)
    model = voice.get("model", DEFAULT_MODEL)
    speed = float(voice.get("speed", 1.0))
    temperature = float(voice.get("temperature", 0.65))
    top_p = float(voice.get("top_p", 0.7))
    regenerate = bool(voice.get("regenerate", False))
    narration_dir = project / "audio" / "narration"
    for beat in doc["beats"]:
        text = str(beat.get("narration", "")).strip()
        if not text:
            raise SystemExit(f"beat {beat.get('id')} has no narration")
        target = narration_dir / f"beat_{int(beat['id']):02d}.wav"
        made = regenerate or not target.is_file()
        if made:
            synthesize(
                text,
                reference_id,
                target,
                model=model,
                speed=speed,
                temperature=temperature,
                top_p=top_p,
            )
        else:
            print(f"reused narration for beat {beat['id']}")
        beat["narration_audio"] = str(target.resolve())
        if made:
            print(f"generated narration for beat {beat['id']}")
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audition = sub.add_parser("audition", help="generate the six curated Chinese male auditions")
    audition.add_argument("output_dir")
    audition.add_argument("--text", default=AUDITION_TEXT)
    project = sub.add_parser("project", help="generate narration for every beat")
    project.add_argument("project_dir")
    args = parser.parse_args()
    if args.command == "audition":
        generate_auditions(args.output_dir, args.text)
    else:
        generate_project(args.project_dir)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate or validate narration, then validate music for assembly.

Liblib's documented workflow API generates images/video, not a stable TTS/BGM
service. Fish Audio is the optional TTS provider; local narration remains valid.
"""
import json, os, re, subprocess, sys, wave
from fish_audio import generate_project

EDGE_TRIM = (
    "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB:"
    "start_silence=0.03,areverse,"
    "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB:"
    "start_silence=0.03,areverse"
)

def probe_dur(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
        value = float(out.strip())
        if value > 0:
            return value
    except OSError:
        pass
    except ValueError:
        pass
    # ffprobe is not bundled by every macOS ffmpeg distribution. Fall back to
    # ffmpeg's input summary so assembly works with an ffmpeg-only install.
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if value > 0:
                return value
    except OSError:
        pass
    if str(path).lower().endswith(".wav"):
        try:
            with wave.open(path, "rb") as audio:
                value = audio.getnframes() / float(audio.getframerate())
                # Streaming WAVs may use 0x7fffffff as an unknown-length sentinel.
                return value if value < 24 * 60 * 60 else 0.0
        except (wave.Error, OSError, ZeroDivisionError):
            pass
    return 0.0

def trim_edges(source, target):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(source):
        return
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", source,
        "-af", EDGE_TRIM, "-ar", "48000", "-ac", "1", target
    ], check=True)

def run(project_dir):
    bpath = os.path.join(project_dir, "beats.json")
    with open(bpath) as f: doc = json.load(f)
    if (doc.get("voice") or {}).get("provider") == "fish":
        generate_project(project_dir)
        with open(bpath) as f: doc = json.load(f)
        if (doc.get("voice") or {}).get("trim_silence", True):
            trim_dir = os.path.join(project_dir, "audio", "narration", "trimmed")
            for beat in doc["beats"]:
                source = beat["narration_audio"]
                target = os.path.join(trim_dir, os.path.basename(source))
                trim_edges(source, target)
                beat["narration_audio"] = os.path.abspath(target)
    missing = []
    for beat in doc["beats"]:
        path = beat.get("narration_audio")
        if not path or not os.path.isfile(path): missing.append(f"beat {beat['id']}: narration_audio")
        else: beat["narration_dur"] = round(probe_dur(path), 2)
    bgm = doc.get("bgm_path")
    if not bgm or not os.path.isfile(bgm): missing.append("bgm_path")
    else: doc["bgm_dur"] = round(probe_dur(bgm), 2)
    if missing:
        raise SystemExit("Provide the remaining local audio files before assembly: " + ", ".join(missing))
    with open(bpath, "w") as f: json.dump(doc, f, ensure_ascii=False, indent=2)
    print("audio inputs validated ->", bpath)

if __name__ == "__main__":
    run(os.path.abspath(sys.argv[1]))

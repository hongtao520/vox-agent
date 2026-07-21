#!/usr/bin/env python3
"""
Assembly stage (ffmpeg): multi-shot clips + per-beat narration + music -> final.mp4

Model: beats -> shots. Each shot is one short clip (its own cut). Narration and
captions are per BEAT and span all the beat's shots, so the voice stays aligned
while the visuals cut. BGM is ducked under the narration. Captions + watermark
are Pillow PNGs composited with `overlay` (this ffmpeg has no libass/drawtext).

Usage: python3 assemble.py <project_dir>   (default: out/tang-30s)
"""
import json
import os
import re
import subprocess
import sys

import text_overlay

FPS, TAIL = 24, 0.5
WATERMARK = "AI generated · vox-agent"
RES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


def ff(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def probe_dur(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    except OSError:
        out = ""
    try:
        return float(out.strip())
    except ValueError:
        pass
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except OSError:
        pass
    return 0.0


def shots_of(beat):
    if beat.get("shots"):
        for s in beat["shots"]:
            yield s
    else:
        yield beat


def run(project_dir):
    with open(os.path.join(project_dir, "beats.json")) as f:
        doc = json.load(f)
    beats = doc["beats"]
    W, H = RES.get(doc.get("aspect", "16:9"), (1920, 1080))
    wm_text = doc.get("watermark", WATERMARK)
    mix = doc.get("mix", {})                      # per-project audio balance (optional)
    music_vol = float(mix.get("music", 0.7))      # audible music bed while leaving narration in front
    voice_vol = float(mix.get("voice", 1.25))     # narration boost before the duck + final mix
    duck_threshold = float(mix.get("duck_threshold", 0.1))
    duck_ratio = float(mix.get("duck_ratio", 2.0))
    duck_attack = float(mix.get("duck_attack_ms", 10))
    duck_release = float(mix.get("duck_release_ms", 180))
    master_vol = float(mix.get("master", 0.8))
    cap_style = doc.get("caption_style", "white") # white (default, clean) | paper (collage)
    timing = doc.get("narration_timing", {})
    timing_mode = timing.get("mode", "continuous")
    narration_gap = max(0.0, float(timing.get("gap_s", 0.1)))
    narration_lead = max(0.0, float(timing.get("lead_in_s", 0.12)))
    narration_tail = max(0.0, float(timing.get("tail_s", TAIL)))
    tmp = os.path.join(project_dir, "_seg")
    os.makedirs(tmp, exist_ok=True)

    # ---- flatten shots into timed segments; track each beat's span ----
    segs = []          # {clip, dur}
    beat_spans = []    # {start, dur, beat}
    narration_spans = []  # voice/caption timing, independent from fixed beat slots
    base_total = sum(float(s.get("dur", 10)) for beat in beats for s in shots_of(beat))
    if timing_mode == "continuous":
        required = (narration_lead
                    + sum(float(b.get("narration_dur", 0)) for b in beats)
                    + narration_gap * max(len(beats) - 1, 0) + narration_tail)
        planned_total = max(base_total, required)
        visual_targets, used = [], 0.0
        for i, beat in enumerate(beats):
            if i < len(beats) - 1:
                target = float(beat.get("narration_dur", 0)) + narration_gap
                if i == 0:
                    target += narration_lead
            else:
                target = planned_total - used
            target = max(target, 0.1)
            visual_targets.append(target)
            used += target
    else:
        visual_targets = [None] * len(beats)

    t = 0.0
    voice_t = narration_lead if timing_mode == "continuous" else 0.0
    for beat_index, beat in enumerate(beats):
        beat_start = t
        shot_list = list(shots_of(beat))
        durs = [float(s.get("dur", 10)) for s in shot_list]
        if timing_mode == "continuous":
            # Move visual cuts to the voice handoffs while preserving the requested
            # total runtime. Multi-shot beats scale proportionally inside their span.
            target = visual_targets[beat_index]
            original = sum(durs) or 1.0
            durs = [d * target / original for d in durs]
            durs[-1] += target - sum(durs)
        else:
            # Legacy beat-locked mode: each line starts at its visual beat boundary.
            need = float(beat.get("narration_dur", sum(durs))) + narration_tail
            if sum(durs) < need:
                durs[-1] += need - sum(durs)
        for s, d in zip(shot_list, durs):
            segs.append({"clip": s["clip_path"], "dur": round(d, 2)})
            t += round(d, 2)
        beat_spans.append({"start": beat_start, "dur": round(t - beat_start, 2), "beat": beat})
        narration_start = voice_t if timing_mode == "continuous" else beat_start
        narration_dur = float(beat.get("narration_dur", 0))
        narration_spans.append({"start": narration_start, "dur": narration_dur, "beat": beat})
        if timing_mode == "continuous":
            voice_t += narration_dur
            if beat_index < len(beats) - 1:
                voice_t += narration_gap
    total = round(t, 2)

    with open(os.path.join(project_dir, "assembly_timing.json"), "w") as f:
        json.dump({
            "mode": timing_mode,
            "gap_s": narration_gap if timing_mode == "continuous" else None,
            "lead_in_s": narration_lead if timing_mode == "continuous" else None,
            "tail_s": narration_tail,
            "total_s": total,
            "beats": [{
                "id": ns["beat"]["id"],
                "voice_start_s": round(ns["start"], 3),
                "voice_end_s": round(ns["start"] + ns["dur"], 3),
                "visual_start_s": round(bs["start"], 3),
                "visual_end_s": round(bs["start"] + bs["dur"], 3),
            } for ns, bs in zip(narration_spans, beat_spans)]
        }, f, ensure_ascii=False, indent=2)

    # ---- 1) normalise each shot to a silent segment of exactly its dur ----
    seg_files = []
    for i, s in enumerate(segs):
        out = os.path.join(tmp, f"seg_{i:02d}.mp4")
        # If the clip is shorter than the segment (narration longer than the AI
        # clip), slow it to fill instead of freezing the last frame.
        cd = probe_dur(s["clip"])
        factor = s["dur"] / cd if cd > 0 else 1.0
        pre = f"setpts={factor:.4f}*PTS," if factor > 1.02 else ""
        # blurred-fill background so off-aspect clips (e.g. 3:4 card in 9:16) get a
        # nice bg instead of black bars; for matching-aspect clips the fg fills fully.
        fc = (f"[0:v]{pre}split[s0][s1];"
              f"[s0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=26:2,eq=brightness=-0.05[bg];"
              f"[s1]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},"
              f"tpad=stop_mode=clone:stop_duration=1[v]")
        ff(["-i", s["clip"], "-an", "-filter_complex", fc, "-map", "[v]", "-t", f"{s['dur']}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", out])
        seg_files.append(out)

    # ---- 2) concat all shot segments (video only) ----
    listf = os.path.join(tmp, "list.txt")
    with open(listf, "w") as f:
        for s in seg_files:
            f.write(f"file '{os.path.abspath(s)}'\n")
    body = os.path.join(tmp, "body_silent.mp4")
    ff(["-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", body])

    # ---- 3) captions (per beat) + watermark PNGs ----
    captions_on = bool(doc.get("captions", True))  # "captions": false -> no burned-in captions
    cap_pngs = []
    if captions_on:
        for bs in narration_spans:
            beat = bs["beat"]
            p = os.path.join(tmp, f"cap_{beat['id']}.png")
            acc = None
            if cap_style == "paper":              # only the paper style uses a per-beat keyline
                kf = next((s["keyframe_path"] for s in (beat.get("shots") or [beat])
                           if s.get("keyframe_path") and os.path.exists(s["keyframe_path"])), None)
                acc = text_overlay.accent_color(kf) if kf else None
            text_overlay.render_caption(beat["narration"], p, W, H, accent=acc, style=cap_style)
            cap_pngs.append(p)
    title_items = []
    for bs in beat_spans:
        title = bs["beat"].get("post_title")
        if title:
            p = os.path.join(tmp, f"title_{bs['beat']['id']}.png")
            text_overlay.render_title(title, p, W, H)
            title_items.append((p, bs))
    wm_png = text_overlay.render_watermark(wm_text, os.path.join(tmp, "wm.png"), W, H)

    # ---- 4) one pass: overlay captions+wm, mix per-beat narration, duck BGM ----
    nb = len(beat_spans)
    ncap = len(cap_pngs)                        # 0 when captions are off
    inputs = ["-i", body]                       # 0
    for p in cap_pngs:
        inputs += ["-i", p]                     # 1..ncap
    title_base = ncap + 1
    for p, _ in title_items:
        inputs += ["-i", p]
    wm_idx = title_base + len(title_items)
    inputs += ["-i", wm_png]
    narr_base = wm_idx + 1
    for bs in beat_spans:
        inputs += ["-i", bs["beat"]["narration_audio"]]   # narr inputs
    bgm_idx = narr_base + nb
    inputs += ["-i", doc["bgm_path"]]

    chain, prev = [], "[0:v]"
    for i, bs in enumerate(narration_spans[:ncap]):
        s = bs["start"]
        e = min(total, bs["start"] + bs["dur"] + 0.08)
        lbl = f"[v{i+1}]"
        chain.append(f"{prev}[{i+1}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'{lbl}")
        prev = lbl
    for i, (_, bs) in enumerate(title_items):
        s, e = bs["start"] + 0.12, min(bs["start"] + 2.75, bs["start"] + bs["dur"] - 0.1)
        lbl = f"[vt{i+1}]"
        chain.append(f"{prev}[{title_base+i}:v]overlay=0:0:enable='between(t,{s:.2f},{e:.2f})'{lbl}")
        prev = lbl
    chain.append(f"{prev}[{wm_idx}:v]overlay=0:0[v]")

    # per-beat narration delayed to its start, then mixed
    nlabels = []
    for i, bs in enumerate(narration_spans):
        ms = int(bs["start"] * 1000)
        chain.append(f"[{narr_base+i}:a]adelay={ms}:all=1[n{i}]")
        nlabels.append(f"[n{i}]")
    # pad the narration mix to the FULL duration, else sidechaincompress follows the (shorter)
    # narration length and -shortest clips the tail (e.g. a silent payoff/ending beat).
    chain.append(f"{''.join(nlabels)}amix=inputs={nb}:normalize=0:duration=longest,volume={voice_vol},"
                 f"apad,atrim=0:{total},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[narrmix]")
    # a filter-output label can only be consumed once -> split narration in two
    chain.append("[narrmix]asplit=2[narrA][narrB]")
    chain.append(f"[{bgm_idx}:a]atrim=0:{total},volume={music_vol},"
                 f"afade=t=out:st={max(total-2,0):.2f}:d=2,"
                 "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[bgt]")
    chain.append(
        f"[bgt][narrA]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:"
        f"attack={duck_attack}:release={duck_release}[bgd]"
    )
    chain.append(
        f"[narrB][bgd]amix=inputs=2:normalize=0:duration=longest,volume={master_vol},"
        f"alimiter=limit=0.89:attack=5:release=50:level=false,atrim=0:{total}[a]"
    )
    filt = ";".join(chain)

    final = os.path.join(project_dir, "final.mp4")
    ff([*inputs, "-filter_complex", filt, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", "-shortest", final])
    print("FINAL:", final, f"(~{total}s, {len(segs)} shots)")


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "out", "tang-30s")
    run(os.path.abspath(proj))

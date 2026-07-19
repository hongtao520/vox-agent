#!/usr/bin/env python3
"""
Generate a confetti / torn-paper-scrap overlay clip (on black, for screen-blend).
Adds the constant tactile motion that gives collage explainers their energy.

Usage: python3 confetti.py <out.mp4> [W H seconds]
"""
import os
import random
import subprocess
import sys
import tempfile
from PIL import Image, ImageDraw

random.seed(7)
COLORS = [(212, 175, 55), (240, 240, 235), (200, 50, 40), (40, 120, 120),
          (230, 210, 120), (180, 140, 30)]


def run(out, W=540, H=960, secs=6.0, fps=24, n=70):
    frames = int(secs * fps)
    parts = []
    for _ in range(n):
        parts.append(dict(
            x=random.uniform(0, W), y=random.uniform(-H, H),
            vy=random.uniform(0.6, 2.0), vx=random.uniform(-0.6, 0.6),
            w=random.randint(6, 16), h=random.randint(8, 22),
            rot=random.uniform(0, 360), vr=random.uniform(-6, 6),
            col=random.choice(COLORS), flut=random.uniform(0.5, 1.5)))
    tmp = tempfile.mkdtemp()
    for f in range(frames):
        img = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(img)
        for p in parts:
            p["y"] += p["vy"] + 0.5
            p["x"] += p["vx"] + 0.6 * __import__("math").sin(f * 0.05 * p["flut"])
            p["rot"] += p["vr"]
            if p["y"] > H + 20:
                p["y"] = random.uniform(-40, -10); p["x"] = random.uniform(0, W)
            chip = Image.new("RGBA", (p["w"], p["h"]), p["col"] + (255,))
            chip = chip.rotate(p["rot"], expand=True)
            img.paste(chip, (int(p["x"]), int(p["y"])), chip)
        img.save(os.path.join(tmp, f"c_{f:04d}.png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(tmp, "c_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
    print("confetti ->", out, f"({frames}f, {W}x{H})")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "confetti.mp4"
    run(out)

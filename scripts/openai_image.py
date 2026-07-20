#!/usr/bin/env python3
"""GPT Image 2 client used by the Vox keyframe stages.

Images are written directly to local files.  The later Liblib/Kling stage
uploads those files with Liblib's signed upload API; OpenAI URLs are never
passed between stages.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from credentials import load_skill_env


load_skill_env()


class OpenAIImageError(RuntimeError):
    pass


IMAGE_SIZES = {
    "16:9": "1536x1024",
    "4:3": "1536x1024",
    "9:16": "1024x1536",
    "3:4": "1024x1536",
    "1:1": "1024x1024",
}

ASPECT_RATIOS = {
    "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3,
    "3:4": 3 / 4, "1:1": 1.0,
}


def normalize_aspect(path, aspect):
    """Center-crop a generated image to the project's exact target aspect."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise OpenAIImageError(
            "Pillow is required to normalize GPT Image 2 keyframes; install it with "
            "python3 -m pip install Pillow"
        ) from exc

    target = ASPECT_RATIOS.get(aspect)
    if not target:
        return str(Path(path).resolve())
    image = Image.open(path)
    width, height = image.size
    current = width / height
    if abs(current - target) < 0.002:
        return str(Path(path).resolve())
    if current > target:
        new_width = max(1, round(height * target))
        left = (width - new_width) // 2
        box = (left, 0, left + new_width, height)
    else:
        new_height = max(1, round(width / target))
        top = (height - new_height) // 2
        box = (0, top, width, top + new_height)
    image.crop(box).save(path)
    return str(Path(path).resolve())


class OpenAIImageClient:
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, config=None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", self.DEFAULT_BASE_URL).rstrip("/")
        key_env = self.config.get("api_key_env", "OPENAI_API_KEY")
        self.api_key = os.environ.get(key_env, "").strip()
        if not self.api_key:
            raise OpenAIImageError(
                f"{key_env} must be set for GPT Image 2 keyframes. "
                "Run scripts/configure_credentials.py; never put the key in beats.json."
            )
        self.timeout_s = int(self.config.get("timeout_s", 300))
        self.max_retries = int(self.config.get("max_retries", 3))

    @staticmethod
    def size_for(aspect):
        return IMAGE_SIZES.get(aspect, IMAGE_SIZES["16:9"])

    def generate(self, prompt, dest, *, model="gpt-image-2", aspect="16:9",
                 quality="medium", output_format="png"):
        body = {
            "model": model,
            "prompt": prompt,
            "size": self.size_for(aspect),
            "quality": quality,
            "output_format": output_format,
            "n": 1,
        }
        req = Request(
            self.base_url + "/images/generations",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        data = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout_s) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:1200]
                if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    raise OpenAIImageError(f"OpenAI image HTTP {exc.code}: {detail}") from exc
                time.sleep(min(30, 2 ** attempt * 3))
            except (URLError, TimeoutError, ValueError) as exc:
                if attempt >= self.max_retries:
                    raise OpenAIImageError(f"OpenAI image request failed: {exc}") from exc
                time.sleep(min(30, 2 ** attempt * 3))

        items = data.get("data") if isinstance(data, dict) else None
        item = items[0] if items else {}
        raw = item.get("b64_json")
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        if raw:
            try:
                Path(dest).write_bytes(base64.b64decode(raw))
            except (ValueError, TypeError) as exc:
                raise OpenAIImageError("GPT Image 2 returned invalid base64 image data") from exc
        elif item.get("url"):
            with urlopen(item["url"], timeout=120) as src:
                Path(dest).write_bytes(src.read())
        else:
            raise OpenAIImageError(
                "GPT Image 2 response contained neither b64_json nor url: "
                + json.dumps(data, ensure_ascii=False)[:800]
            )
        return normalize_aspect(dest, aspect)

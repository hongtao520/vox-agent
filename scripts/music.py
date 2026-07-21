#!/usr/bin/env python3
"""Generate a narration-friendly instrumental BGM with a local ACE-Step API.

ACE-Step runs on the user's machine, so this stage needs no cloud music key.
Start the official server first with ``uv run acestep-api`` (default port 8001).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen


DEFAULT_URL = "http://127.0.0.1:8001"
INSTALL_HELP = """ACE-Step local music service is not reachable.

Install it once (free, model download required on first launch):
  git clone https://github.com/ACE-Step/ACE-Step-1.5.git ~/ACE-Step-1.5
  cd ~/ACE-Step-1.5
  uv sync
  uv run acestep-api

Then leave that terminal open and rerun this command. On Apple Silicon ACE-Step uses MPS.
Override the address with music.api_url in beats.json or ACESTEP_API_URL.
"""


def _open(req: Request, timeout: float):
    """Open loopback requests without inheriting an HTTP proxy."""
    host = (urlparse(req.full_url).hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return build_opener(ProxyHandler({})).open(req, timeout=timeout)
    return urlopen(req, timeout=timeout)


def _request(base_url: str, path: str, payload=None, timeout: float = 30):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.environ.get("ACESTEP_API_KEY", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), data=data, headers=headers)
    try:
        with _open(req, timeout=timeout) as response:
            body = response.read()
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"ACE-Step request failed at {path}: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ACE-Step returned invalid JSON at {path}") from exc


def _project_duration(doc: dict) -> float:
    total = 0.0
    for beat in doc.get("beats", []):
        shots = beat.get("shots") or [beat]
        total += sum(float(shot.get("dur", 10)) for shot in shots)
    return max(total, 10.0)


def _default_prompt(doc: dict) -> str:
    topic = str(doc.get("topic") or doc.get("project") or "documentary story").strip()
    feelings = [str(beat.get("feel", "")).strip() for beat in doc.get("beats", [])]
    feelings = ", ".join(dict.fromkeys(item for item in feelings if item))
    mood = f" Emotional arc: {feelings}." if feelings else ""
    return (
        f"Instrumental cinematic documentary underscore for: {topic}.{mood} "
        "Narration-friendly sparse arrangement, restrained percussion, clear emotional build, "
        "no vocals, no chanting, no speech-like lead melody, no abrupt opening, decisive clean ending."
    )


def _unwrap(response: dict, action: str):
    if not isinstance(response, dict) or response.get("code") not in (None, 200):
        raise RuntimeError(f"ACE-Step {action} failed: {response.get('error') if isinstance(response, dict) else response}")
    return response.get("data", response)


def generate(project_dir: str) -> str:
    project = Path(project_dir).resolve()
    beats_path = project / "beats.json"
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    music = doc.get("music") or {}
    if music.get("enabled", True) is False:
        raise RuntimeError("music.enabled is false and no valid bgm_path was provided")
    provider = str(music.get("provider", "ace-step")).lower()
    if provider not in {"ace-step", "acestep", "local"}:
        raise RuntimeError(f"Unsupported free music provider: {provider}")

    output = project / "audio" / "bgm.wav"
    if output.is_file() and not music.get("regenerate", False):
        doc["bgm_path"] = str(output)
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print("reusing local BGM ->", output)
        return str(output)

    base_url = str(music.get("api_url") or os.environ.get("ACESTEP_API_URL") or DEFAULT_URL)
    try:
        health = _unwrap(_request(base_url, "/health", timeout=5), "health check")
    except RuntimeError as exc:
        raise SystemExit(f"{exc}\n\n{INSTALL_HELP}") from exc
    if isinstance(health, dict) and health.get("status") not in (None, "ok"):
        raise SystemExit(f"ACE-Step service is not ready: {health}\n\n{INSTALL_HELP}")

    video_duration = _project_duration(doc)
    duration = max(10.0, float(music.get("duration_s", video_duration + 2.0)))
    payload = {
        "prompt": str(music.get("prompt") or _default_prompt(doc)),
        "lyrics": "[Instrumental]",
        "instrumental": True,
        "audio_duration": min(duration, 600.0),
        "audio_format": "wav",
        "model": str(music.get("model", "acestep-v15-turbo")),
        "inference_steps": int(music.get("inference_steps", 8)),
        "batch_size": 1,
        "thinking": bool(music.get("thinking", False)),
        "use_random_seed": "seed" not in music,
    }
    if "seed" in music:
        payload["seed"] = int(music["seed"])

    submitted = _unwrap(_request(base_url, "/release_task", payload, timeout=30), "submission")
    task_id = submitted.get("task_id") if isinstance(submitted, dict) else None
    if not task_id:
        raise RuntimeError(f"ACE-Step did not return a task_id: {submitted}")

    deadline = time.monotonic() + float(music.get("timeout_s", 1800))
    poll_s = max(1.0, float(music.get("poll_s", 3)))
    while time.monotonic() < deadline:
        try:
            queried = _unwrap(
                _request(base_url, "/query_result", {"task_id_list": [task_id]}, timeout=30),
                "status query",
            )
        except RuntimeError as exc:
            # First-run model downloads/initialization can block the local API for
            # longer than one HTTP timeout. Keep polling the same task so a slow
            # local start never causes a duplicate music submission.
            print(f"ACE-Step is still initializing ({exc}); waiting...", file=sys.stderr)
            time.sleep(poll_s)
            continue
        task = queried[0] if isinstance(queried, list) and queried else {}
        status = task.get("status")
        if status == 2:
            raise RuntimeError(f"ACE-Step music generation failed: {task.get('result') or task}")
        if status == 1:
            result = task.get("result")
            if isinstance(result, str):
                result = json.loads(result)
            item = result[0] if isinstance(result, list) and result else result
            file_url = item.get("file") if isinstance(item, dict) else None
            if not file_url:
                raise RuntimeError(f"ACE-Step completed without an audio URL: {task}")
            token = os.environ.get("ACESTEP_API_KEY", "").strip()
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            req = Request(urljoin(base_url.rstrip("/") + "/", file_url.lstrip("/")), headers=headers)
            output.parent.mkdir(parents=True, exist_ok=True)
            with _open(req, timeout=120) as response, output.open("wb") as target:
                shutil.copyfileobj(response, target)
            if output.stat().st_size == 0:
                raise RuntimeError("ACE-Step downloaded an empty audio file")
            doc["bgm_path"] = str(output)
            doc.setdefault("music", {}).update({"provider": "ace-step", "instrumental": True})
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            print("local ACE-Step BGM ->", output)
            return str(output)
        time.sleep(poll_s)
    raise RuntimeError(f"ACE-Step task timed out after {music.get('timeout_s', 1800)} seconds: {task_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/music.py out/<project>")
    generate(sys.argv[1])

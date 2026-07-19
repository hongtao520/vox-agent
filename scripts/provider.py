#!/usr/bin/env python3
"""Provider abstraction for Liblib visual generation and local downloads."""
import time
from abc import ABC, abstractmethod
from liblib_api import LiblibClient, LiblibError


class ProviderError(RuntimeError): pass


class Provider(ABC):
    name = "base"
    @abstractmethod
    def submit_image(self, model, prompt, **params): pass
    @abstractmethod
    def submit_video(self, model, prompt, **params): pass
    @abstractmethod
    def get_status(self, job_id): pass
    @abstractmethod
    def upload(self, path): pass
    @abstractmethod
    def download(self, url, dest): pass


IMAGE_SIZES = {
    "16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024),
    "3:4": (768, 1024), "4:3": (1024, 768),
}

DEFAULT_IMAGE_API = {
    "submit_path": "/api/generate/webui/text2img/ultra",
    "status_path": "/api/generate/webui/status",
    "submit_body": {
        "templateUuid": "5d7e67009b344550bc1aa6ccbfa1d7f4",
        "generateParams": {
            "prompt": "${prompt}",
            "imageSize": {"width": "${width}", "height": "${height}"},
            "imgCount": 1,
            "steps": "${steps}"
        }
    }
}

DEFAULT_VIDEO_API = {
    "submit_path": "/api/generate/video/kling/img2video",
    "status_path": "/api/generate/status",
    "submit_body": {
        "templateUuid": "180f33c6748041b48593030156d2a71d",
        "generateParams": {
            "model": "${kling_model}", "prompt": "${prompt}",
            "promptMagic": "${prompt_magic}", "mode": "${mode}",
            "startFrame": "${image}", "duration": "${duration}"
        }
    }
}


class LiblibProvider(Provider):
    """Use Star-3 for keyframes and Kling image-to-video by default.

    Projects may replace either request definition with image_api/video_api, or
    provide an exact ComfyUI request as image_workflow/video_workflow.
    """
    name = "liblib"
    def __init__(self, config=None):
        self.config = config or {}
        self.client = LiblibClient(self.config)
        self.max_concurrency = int(self.config.get("max_concurrency", 5))
        self.submit_interval_s = float(self.config.get("submit_interval_s", 1.05))
        self._last_submit_at = 0.0

    def _submit(self, api, prompt, values):
        wait = self.submit_interval_s - (time.time() - self._last_submit_at)
        if wait > 0:
            time.sleep(wait)
        task = self.client.submit(api, prompt=prompt, params=values)
        self._last_submit_at = time.time()
        return task

    def submit_image(self, model, prompt, **params):
        api = self.config.get("image_api") or self.config.get("image_workflow") or DEFAULT_IMAGE_API
        aspect = params.get("aspect_ratio", "16:9")
        width, height = IMAGE_SIZES.get(aspect, IMAGE_SIZES["16:9"])
        values = {**params, "width": width, "height": height,
                  "steps": int(self.config.get("image_steps", 30))}
        return self._submit(api, prompt, values)

    def submit_video(self, model, prompt, **params):
        api = self.config.get("video_api") or self.config.get("video_workflow") or DEFAULT_VIDEO_API
        requested = int(params.get("duration", 5))
        values = {
            **params,
            "duration": "5" if requested <= 5 else "10",
            "kling_model": self.config.get("kling_model", "kling-v2-1"),
            "prompt_magic": int(self.config.get("prompt_magic", 0)),
            "mode": self.config.get("video_mode", "std"),
        }
        return self._submit(api, prompt, values)

    def get_status(self, job_id):
        try:
            return self.client.status(job_id)
        except LiblibError as exc:
            # Liblib may return moderation/model failures as a non-zero API code
            # from the status endpoint. Normalize those into the provider contract
            # so run_jobs can retry or report a per-shot failure without aborting
            # every unrelated queued task.
            return {"status": "failed", "output": None, "error": str(exc)}

    def upload(self, path):
        if str(path).startswith(("http://", "https://")): return path
        raise ProviderError("Liblib workflow API needs a public image URL. Put the asset on an HTTPS URL and use keyframe_url/anchor_photo URL; local-file upload is not part of this backend.")

    def download(self, url, dest): return self.client.download(url, dest)


def get_provider(name=None, config=None):
    name = (name or "liblib").lower()
    if name not in {"liblib", "liblibtv"}:
        raise ProviderError("only the Liblib backend is installed; set provider to 'liblib'")
    return LiblibProvider(config)


def run_jobs(prov, specs, *, poll_s=3, stall_s=90, max_retries=2, deadline_s=900):
    """Run a bounded async queue; Liblib defaults to QPS=1 and concurrency=5."""
    queue, active, done = list(specs), {}, {}
    deadline = time.time() + deadline_s
    limit = max(1, int(getattr(prov, "max_concurrency", 5)))

    submit_backoff_s = float(getattr(prov, "config", {}).get("submit_backoff_s", 15))

    def launch(key, tries=0):
        try:
            pid = specs[key]()
        except LiblibError as exc:
            message = str(exc)
            transient = any(token in message.lower() for token in (
                "并发", "频率", "上限", "稍后", "too many", "rate limit", "429"
            ))
            if not transient:
                raise
            print(f"[{key}] submit deferred ({message[:100]}); retrying in {submit_backoff_s:g}s")
            return False
        active[key] = {"pid": pid, "t": time.time(), "tries": tries}
        print(f"[{key}] submitted")
        return True

    while queue and len(active) < limit:
        key = queue.pop(0)
        if not launch(key):
            queue.insert(0, key)
            time.sleep(submit_backoff_s)
            break

    while (active or queue) and time.time() < deadline:
        time.sleep(poll_s if active else submit_backoff_s)
        now = time.time()
        for key in list(active):
            state = active[key]
            result = prov.get_status(state["pid"])
            failed = result["status"] == "failed"
            stalled = result["status"] == "pending" and now - state["t"] > stall_s
            if result["status"] == "completed":
                done[key] = result["output"]
                del active[key]
                print(f"[{key}] done")
            elif failed or stalled:
                if state["tries"] < max_retries:
                    tries = state["tries"] + 1
                    del active[key]
                    if launch(key, tries):
                        print(f"[{key}] retry {tries}")
                    else:
                        queue.insert(0, key)
                else:
                    done[key] = None
                    del active[key]
                    why = result.get("error") or (f"stalled>{stall_s}s" if stalled else "failed")
                    print(f"[{key}] FAILED: {why[:120]}")
        while queue and len(active) < limit:
            key = queue.pop(0)
            if not launch(key):
                queue.insert(0, key)
                break

    for key in specs:
        done.setdefault(key, None)
    return done

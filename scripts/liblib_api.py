#!/usr/bin/env python3
"""Small, dependency-free client for LiblibAI workflow generation.

The public Liblib workflow API is asynchronous: submit a ComfyUI application,
then poll its task id until an image or video URL is available.  Workflow node
names are intentionally supplied by the project, rather than being guessed in
code: every API-enabled Liblib workflow exposes a different input contract.

Credentials are read only from LIBLIB_ACCESS_KEY and LIBLIB_SECRET_KEY (or the
explicit environment variable names in ``provider_config``); they are never
stored in beats.json. Liblib signs URL query parameters, not Bearer headers.
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from credentials import load_skill_env


load_skill_env()


class LiblibError(RuntimeError):
    pass


class LiblibClient:
    DEFAULT_BASE_URL = "https://openapi.liblibai.cloud"

    def __init__(self, config=None):
        self.config = config or {}
        self.base_url = self.config.get("base_url", self.DEFAULT_BASE_URL).rstrip("/")
        self.access_key = os.environ.get(self.config.get("access_key_env", "LIBLIB_ACCESS_KEY"))
        self.secret_key = os.environ.get(self.config.get("secret_key_env", "LIBLIB_SECRET_KEY"))
        if not self.access_key or not self.secret_key:
            raise LiblibError("LIBLIB_ACCESS_KEY and LIBLIB_SECRET_KEY must be set. Do not put either key in beats.json.")

    def _signed_url(self, path):
        timestamp = str(int(time.time() * 1000))
        nonce = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(16))
        content = f"{path}&{timestamp}&{nonce}".encode("utf-8")
        digest = hmac.new(self.secret_key.encode("utf-8"), content, hashlib.sha1).digest()
        signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return self.base_url + path + "?" + urlencode({"AccessKey": self.access_key, "Signature": signature, "Timestamp": timestamp, "SignatureNonce": nonce})

    def _request(self, path, body):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = Request(self._signed_url(path), data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(req, timeout=int(self.config.get("timeout_s", 45))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise LiblibError(f"Liblib HTTP {exc.code}: {detail}") from exc
        except (URLError, ValueError) as exc:
            raise LiblibError(f"Liblib request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise LiblibError("Liblib returned a non-object JSON response")
        code = data.get("code")
        if code not in (None, 0, 200, "0", "200"):
            raise LiblibError(data.get("msg") or data.get("message") or f"Liblib error code {code}")
        return data

    @staticmethod
    def _lookup(data, dotted):
        cur = data
        for part in dotted.split("."):
            if isinstance(cur, dict): cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur): cur = cur[int(part)]
            else: return None
        return cur

    @staticmethod
    def _expand(value, values):
        if isinstance(value, str):
            if value.startswith("${") and value.endswith("}") and value.count("${") == 1:
                key = value[2:-1]
                if key in values:
                    return values[key]
            for key, val in values.items(): value = value.replace("${" + key + "}", str(val or ""))
            return value
        if isinstance(value, list): return [LiblibClient._expand(x, values) for x in value]
        if isinstance(value, dict): return {k: LiblibClient._expand(v, values) for k, v in value.items()}
        return value

    def submit(self, workflow, *, prompt, params):
        if not workflow or not workflow.get("submit_path"):
            raise LiblibError("Liblib API configuration needs submit_path")
        values = {"prompt": prompt, **params}
        template = workflow.get("submit_body")
        if not template:
            raise LiblibError("Liblib API configuration needs submit_body")
        body = self._expand(template, values)
        data = self._request(workflow["submit_path"], body)
        task_id = next((self._lookup(data, p) for p in workflow.get("task_id_paths", ["data.generateUuid", "data.taskId", "data.id", "generateUuid", "taskId", "id"]) if self._lookup(data, p)), None)
        if not task_id: raise LiblibError(f"Liblib submit response has no task id: {json.dumps(data, ensure_ascii=False)[:800]}")
        return str(task_id), workflow

    def status(self, task):
        task_id, workflow = task
        template = workflow.get("status_body", {"generateUuid": "${task_id}"})
        data = self._request(workflow.get("status_path", "/api/generate/comfy/status"), self._expand(template, {"task_id": task_id}))
        raw = next((self._lookup(data, p) for p in workflow.get("status_paths", ["data.generateStatus", "data.status", "generateStatus", "status"]) if self._lookup(data, p) is not None), None)
        status = str(raw).lower()
        if status in {"5", "success", "succeeded", "completed", "complete"}:
            paths = workflow.get("output_paths", ["data.images.0.imageUrl", "data.videos.0.videoUrl", "data.output.0.url", "data.output"])
            out = next((self._lookup(data, p) for p in paths if self._lookup(data, p)), None)
            if isinstance(out, list): out = out[0] if out else None
            if isinstance(out, dict): out = out.get("url") or out.get("imageUrl") or out.get("videoUrl")
            if not out:
                return {"status": "failed", "output": None,
                        "error": self._lookup(data, "data.generateMsg") or "Liblib task succeeded but no approved output URL was returned"}
            return {"status": "completed", "output": out, "error": None}
        if status in {"6", "failed", "fail", "error", "rejected"}:
            return {"status": "failed", "output": None,
                    "error": self._lookup(data, "data.generateMsg") or data.get("msg") or data.get("message") or str(data)[:500]}
        return {"status": "pending", "output": None, "error": None}

    def upload(self, path):
        """Upload a local jpg/png to Liblib's temporary OSS and return its HTTPS URL."""
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise LiblibError(f"upload file does not exist: {source}")
        extension = source.suffix.lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png"}:
            raise LiblibError("Liblib upload supports only jpg, jpeg and png")
        if source.stat().st_size > 10 * 1024 * 1024:
            raise LiblibError("Liblib upload image must not exceed 10 MB")

        signed = self._request(
            "/api/generate/upload/signature",
            {"name": source.stem[:100], "extension": extension},
        )
        info = signed.get("data") or {}
        required = {
            "key": info.get("key"),
            "policy": info.get("policy"),
            "x-oss-date": info.get("xOssDate"),
            "x-oss-expires": info.get("xOssExpires"),
            "x-oss-signature": info.get("xOssSignature"),
            "x-oss-credential": info.get("xOssCredential"),
            "x-oss-signature-version": info.get("xOssSignatureVersion"),
        }
        post_url = str(info.get("postUrl") or "").rstrip("/")
        if not post_url or any(value in (None, "") for value in required.values()):
            raise LiblibError(
                "Liblib upload signature response is incomplete: "
                + json.dumps(signed, ensure_ascii=False)[:800]
            )

        boundary = "----vox-director-" + secrets.token_hex(12)
        chunks = []
        for name, value in required.items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(), b"\r\n",
            ])
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{source.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            source.read_bytes(), b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        req = Request(
            post_url,
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=int(self.config.get("upload_timeout_s", 180))) as response:
                if response.status not in {200, 201, 204}:
                    raise LiblibError(f"Liblib OSS upload returned HTTP {response.status}")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise LiblibError(f"Liblib OSS upload HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise LiblibError(f"Liblib OSS upload failed: {exc}") from exc
        return post_url + "/" + quote(str(required["key"]), safe="/")

    @staticmethod
    def download(url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        req = Request(url, headers={"User-Agent": "vox-director-liblib/1.0"})
        with urlopen(req, timeout=120) as src, open(dest, "wb") as out:
            out.write(src.read())
        return dest

# Liblib API routing

Use signed query parameters on every request:

- `AccessKey`, `Signature`, millisecond `Timestamp`, `SignatureNonce`
- signature source: `uri_path&timestamp&nonce`
- signature: HMAC-SHA1 with SecretKey, URL-safe Base64 without trailing `=`
- credentials: `LIBLIB_ACCESS_KEY`, `LIBLIB_SECRET_KEY`
- default submission QPS is 1 and default active-task concurrency is 5; keep
  `submit_interval_s` at least `1.0` and `max_concurrency` at most `5`

## Keyframe routes

- In a Codex task, `image_provider: auto` writes a GPT Image 2 manifest. Treat all
  keyframes in that manifest as one provider batch.
- Outside Codex, `image_provider: auto` sends the complete image batch directly to
  Liblib's text-to-image route.
- In Codex, if any manifest item returns a network/service error, stop all remaining
  Codex image calls and open the circuit for the whole project:

```bash
python3 scripts/keyframe_fallback.py out/<project> --all
```

Do not retry Codex. The fallback submits every project keyframe through Liblib's default text-to-image
template at `POST /api/generate/webui/text2img/ultra`, polls
`POST /api/generate/webui/status`, downloads the result immediately, and records
`keyframe_source.provider: liblib` plus `reason: codex_batch_failed` in `beats.json`.
Already-generated Codex files remain on disk for recovery, but `beats.json` points every
shot at a `_liblib.png` file so the final video never mixes providers.

## Local keyframe upload for Kling

- request a signed upload with `POST /api/generate/upload/signature`
- body: `name` plus `extension` (`jpg`, `jpeg`, or `png`); image limit is 10 MB
- multipart POST the returned OSS fields to `postUrl`; put the `file` field last
- the public input URL is `postUrl + "/" + key`
- the signature expires after one hour; upload immediately before submitting Kling

## Default video route

- submit: `POST /api/generate/video/kling/img2video`
- template: `180f33c6748041b48593030156d2a71d`
- status: `POST /api/generate/status`
- default model: `kling-v2-1`
- request fields for the default `kling-v2-1`: `prompt`, `promptMagic`, `mode`,
  `startFrame`, `duration`. Do not send `sound`; Liblib accepts it only for
  `kling-v2-6` and later.
- duration accepts only `5` or `10`; input image must be a public URL

## Polling

Send `{"generateUuid": "..."}`. Status `5` is success and `6` is failure. Read
`images[0].imageUrl` or `videos[0].videoUrl`. Output URLs normally expire after 7 days;
download them immediately.

## Custom ComfyUI workflows

Submit to `/api/generate/comfyui/app`, poll `/api/generate/comfy/status`, and use:

```json
{
  "templateUuid": "4df2efa0f18d46dc9758803e478eb51c",
  "generateParams": {
    "workflowUuid": "WORKFLOW_VERSION_UUID",
    "76": {"class_type": "SeargePromptCombiner", "inputs": {"prompt1": "${prompt}"}}
  }
}
```

Only published workflows whose detail page shows API parameters are callable. Preserve
the generated node structure exactly and change only documented `inputs` fields.

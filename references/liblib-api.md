# Liblib API routing

Use signed query parameters on every request:

- `AccessKey`, `Signature`, millisecond `Timestamp`, `SignatureNonce`
- signature source: `uri_path&timestamp&nonce`
- signature: HMAC-SHA1 with SecretKey, URL-safe Base64 without trailing `=`
- credentials: `LIBLIB_ACCESS_KEY`, `LIBLIB_SECRET_KEY`
- default submission QPS is 1 and default active-task concurrency is 5; keep
  `submit_interval_s` at least `1.0` and `max_concurrency` at most `5`

## Default keyframe route

- submit: `POST /api/generate/webui/text2img/ultra`
- template: `5d7e67009b344550bc1aa6ccbfa1d7f4` (Star-3 Alpha text-to-image)
- status: `POST /api/generate/webui/status`
- request fields: `templateUuid`, `generateParams.prompt`, `imageSize`, `imgCount`, `steps`

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

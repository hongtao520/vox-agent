# Models & gotchas

Read this before debugging provider failures.

## Model ownership

| Job | Model | Provider |
|---|---|---|
| Keyframe / collage poster | `gpt-image-2` or `liblib-ultra` | Codex chat batch in Codex; complete Liblib batch outside Codex or after a Codex batch failure |
| Animate | `kling-v2-1` | Liblib image-to-video |
| Narration | `s2.1-pro-free` | Fish Audio |
| Assembly, captions, music mix | local | ffmpeg + Pillow |

Use `image_provider: auto`: Codex chat image generation inside Codex, otherwise Liblib.
If any Codex item has a network/service failure, reroute the complete project with
`keyframe_fallback.py --all`. Keep factual Chinese titles out of the generated image;
render `post_title` and captions locally.

## API gotchas

1. Codex chat image generation needs no separate API key. Legacy explicit OpenAI API mode
   requires `OPENAI_API_KEY`, but it is not part of the default three-key setup.
2. Landscape/portrait API sizes may not exactly match the project aspect. The client
   center-crops the generated frame to the exact target before Kling sees it; keep important
   subjects away from extreme edges.
3. Liblib Kling needs a public input URL. `clips.py` uploads local GPT Image 2 PNGs through
   `/api/generate/upload/signature`, then posts the file to the returned OSS endpoint.
4. Liblib upload accepts only jpg/jpeg/png up to 10 MB and its signature expires in one hour.
5. Kling accepts 5- or 10-second requests; shorter timeline shots are trimmed during assembly.

## ffmpeg gotchas

The local ffmpeg may have no libass or drawtext. Render captions and watermarks to PNG with
Pillow, then composite with `overlay`. Normalize off-aspect clips with a blurred-cover
background plus a fitted foreground. Stretch short clips with `setpts` instead of freezing
the last frame. Convert both inputs to the same pixel format before `blend`, and always verify
the final MP4 by extracting representative frames.

## Cost

Treat price as provider-dependent and verify current OpenAI, Liblib and Fish pricing before a
production batch. Codex-native image generation follows the user's Codex entitlement; OpenAI
API mode is billed separately.

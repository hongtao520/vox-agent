# Models & gotchas

Read this before debugging provider failures.

## Model ownership

| Job | Model | Provider |
|---|---|---|
| Keyframe / collage poster | `gpt-image-2` | Codex image generation; optional OpenAI API mode |
| Animate | `kling-v2-1` | Liblib image-to-video |
| Narration | `s2.1-pro-free` | Fish Audio |
| Assembly, captions, music mix | local | ffmpeg + Pillow |

Do not route text-to-image through Liblib. `image_provider` accepts only `codex` or `openai`,
and `image_model` must be GPT Image 2. Keep factual Chinese titles out of the generated image;
render `post_title` and captions locally.

## API gotchas

1. GPT Image 2 API mode requires `OPENAI_API_KEY`; Codex-native mode does not.
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

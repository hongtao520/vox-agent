---
name: vox-agent
description: >
  Turn one topic into a finished Vox-style paper-collage explainer or ad: script, collage
  keyframes, motion, Fish Audio narration, captions, and local ffmpeg assembly. In Codex, GPT Image 2
  assigns one parallel subagent to every keyframe; one network/service failure switches the whole batch to Liblib.
  Outside Codex, Liblib creates all images. Liblib/Kling owns image-to-video and Fish owns voice. Use whenever the user wants a Vox
  video, torn-paper collage animation, motion collage, narrated collage explainer, scrapbook
  tribute, or a Stav Zilber / rom1trs / Higgsfield-style collage ad. Supports a topic (B-roll),
  talking-head video (A-roll), or one anchored person/product photo (C-roll). Triggers include
  "vox video", "collage video", "motion collage", "paper collage explainer", "make a
  collage ad", and "turn this topic/photo/product into a collage video".
---

# Vox Agent

Run the complete workflow from this folder. Do not read scripts, credentials,
templates, or assets from another installed Skill.

Turn a one-line topic into a finished **Vox-style paper-collage video**: a bold, punchy,
narrated explainer/ad where each beat is a torn-paper collage poster that comes alive, with
captions. Keyframes use **GPT Image 2 in Codex** with a whole-project **Liblib fallback**,
motion runs on **Liblib/Kling**, and
assembly runs on local **ffmpeg**.

The look is the modern editorial paper-collage popularized by Vox explainers and creators
like Stav Zilber / rom1trs: hand-cut paper cut-outs, torn edges, tape, halftone dots,
newspaper clippings, bold flat color per beat, big cut-out headlines.

## The core idea (read this first)

The Vox collage look and the collage motion are **two different steps**:

1. **The look is born in the IMAGE step.** Each beat is a finished collage *poster* made by a
   text-to-image model. All the collage DNA (torn paper, cut-outs, halftone, bold color,
   headline text) lives in that image. If the image isn't a rich collage, nothing downstream
   will save it.
2. **The motion is added after.** By default an AI video model animates the whole poster (the
   "living poster" path — simple, automated). For dramatic *piece-by-piece* assembly you cut
   the poster into parts and drive them with the local keyframe engine (advanced path).

Everything hinges on the prompts. **Before writing any image or video prompt, read
`references/prompt-guide.md`** — it has the exact prompt structures that make the difference
between "a real Vox collage" and "a moving PowerPoint".

## First-use setup (mandatory; check before any production step)

- Run `python3 scripts/configure_credentials.py --check` at the start of the first task. If it
  reports missing credentials, pause generation and direct the user to run
  `python3 scripts/configure_credentials.py`. It requests exactly three values in hidden terminal
  prompts: Liblib `AccessKey`, Liblib `SecretKey`, and Fish Audio `API Key`. Get the Liblib pair at
  `https://www.liblib.art/apis` and the Fish key at `https://fish.audio/zh-CN/app/api-keys/`.
  README screenshots show both locations. Never request that users paste secrets into chat.
- Save the three values only in the skill-local `.env` (mode 0600, git-ignored). Codex chat image
  generation uses the current Codex session and needs no separate OpenAI API key. Never put
  credentials in `beats.json` or commit `.env`.
- Run `python3 scripts/configure_credentials.py --check` before a production job. It reports only
  configured/missing status and never prints key values. Environment variables with the same names
  take precedence over the skill-local `.env`.
- Read `references/liblib-api.md` before changing motion routing. It documents the local-PNG
  upload that bridges GPT Image 2 keyframes into Kling image-to-video.
- `command -v ffmpeg ffprobe` — required for assembly (`brew install ffmpeg` on macOS).
- `python3 -c "import PIL"` — Pillow, for captions/watermark overlays.

## Standard workflow (topic → film)

This is the default, most-automated path. Every stage is one script, all driven by a single
`beats.json` per project under `out/<project>/`.

1. **Topic → beat map.** First **read `references/beat-layer.md`** (the story layer) and pick a
   narrative `arc` that fits the topic (`timeline` for history, `pas`/`bab` for ads,
   `how_it_works` for explainers, `man_in_hole` for transformations, …). Then write
   `out/<project>/beats.json` following that arc: **beat-1 headline must be a ≤3s hook**; beat
   count per duration (30s→6–8, 60s→10–12); split each beat into **2 shots** (wide+detail) with
   **per-shot `camera_move` VARIED across adjacent beats** (never repeat; `static` on the payoff)
   and **rich `element_motion`** (see step 4). Each beat: `narration`, `title_cn`/`title_en`,
   `scene`, `bg`, `feel`, `hook`. This draft is the **first mandatory approval gate** — show the
   user the beat map before generating (the aspect-routing approximation in step 4 is the other
   one). Examples in `examples/`.

2. **Pick the visual style (hybrid — do this BEFORE keyframes).** Do not reuse one house style
   for every topic. Read `references/prompt-guide.md` (§5 theme presets); pick 3–4 **theme presets**
   (`styles.THEME_PRESETS`: `american-retro`, `swiss-modern`, `punk-zine`,
   `soviet-constructivist`, `wpa-propaganda`, `70s-groovy`, `chinese-ink`, `atomic-age`,
   `newsprint-editorial`) that fit
   the topic's era/culture/tone — **or compose a custom theme** by mixing the prompt-guide dimensions
   (medium/era/palette/type/finish) when none fit. Match the topic, **not** the language (an
   English film on Chinese history should look Chinese). A theme bundles the whole LOOK layer
   (idiom+palette+type+finish+mood+motion). Run a bake-off and let the user pick by eye — AI
   proposes, the library is the quality floor, the human decides. Set the pick as `"theme"`:
   `python3 scripts/style_bakeoff.py out/<project> american-retro,swiss-modern,punk-zine,atomic-age`
   Set the chosen name as `"collage_style"` in beats.json (keyframes.py reads it).

3. **Keyframes (the collage look).** `python3 scripts/keyframes.py out/<project>`
   Set `image_provider: "auto"` (the default) and `image_model: "gpt-image-2"`.
   - **Inside Codex:** the script writes `keyframes/gpt-image-2-manifest.json`. Read
     `references/codex-parallel-keyframes.md`, count manifest items as `N`, and request exactly
     `N` logical subagents: one image per agent. Start all available agents concurrently; when the
     runtime concurrency cap is lower than `N`, queue the rest and refill slots immediately. The
     root agent must orchestrate and validate, not generate manifest images sequentially. Each
     worker calls Codex image generation once, saves only its assigned PNG at the exact `dest`, and
     never edits JSON. Treat the project as one provider batch. If every item succeeds, rerun the
     script to register paths. If any item has a network/service failure, interrupt unfinished
     image workers, do not retry, and immediately run
     `python3 scripts/keyframe_fallback.py out/<project> --all`. That command creates every
     keyframe with Liblib and points the project at those files; earlier Codex files stay local but
     are not used. Never mix Codex and Liblib keyframes in one finished video.
   - **Outside Codex:** `auto` resolves to Liblib and the script generates the complete keyframe
     batch directly through Liblib. Video remains on Liblib/Kling.
   A content-quality rejection is not a network failure; stop for creative review instead of
   silently switching providers. Explicit `image_provider: "openai"` remains only as a legacy
   unattended API mode and is not part of the default three-key setup.
   Compose prompts with the 5-part structure in `references/prompt-guide.md`. Verify each poster looks like a *real layered collage*
   before animating. For Chinese or factual labels, prefer `"title": false` and add
   `post_title`/captions locally; generative lettering is not reliable enough for facts.

4. **Motion.** `python3 scripts/clips.py out/<project>`
   Animates each poster with **Liblib Kling image-to-video**. Two independent axes
   (see `references/beat-layer.md` §3, tested on our stack):
   • **`camera_move`** — ONE move per shot. Safe/default: `{static, push_in, pull_out, pan, tilt,
     parallax}`. **Bold/experimental** `{orbit, dolly_zoom, roll, whip}` are **available, not
     banned** — they can warp the flat art, so pair with `constraints: loose` and **re-roll**.
     Any custom phrase also passes through.
   • **`element_motion`** — where the energy lives; **AI writes it per beat to fit that scene** (not a
     template). Make it RICH (several elements moving) — be bold. A **hero element flying across
     the frame** (paper bird/plane/coins) is a great **occasional** punch on a key beat, **not
     every shot** (a flyer in every frame reads as a formula).
   `motion_style` = amplitude `calm | punchy | max` (the theme sets a default). **`constraints`**
   = `strict` (default: defect guards on — flat-2D, one-way, no-morph; best for clean text-heavy
   explainers) or `loose` (let the model explore 3D/bold moves; re-roll the misses). **Headline
   text is hard-protected only on shots that have a title** (detail shots without a headline are
   free to go wild). The default uses `kling-v2-1`, 5- or 10-second clips, and follows the
   GPT Image 2 keyframe aspect. Account submission limits are handled by a bounded queue with
   rate-limit/concurrency backoff.

5. **Voice + music.** `python3 scripts/audio.py out/<project>`
   Liblib's documented visual workflow API does not supply TTS or BGM. For narration, either
   set one local `narration_audio` file per beat, or configure `voice.provider: "fish"` with a
   Fish library/clone `reference_id`. Fish credentials come only from `FISH_API_KEY`. If no voice
   block and no complete local narration are provided, default to Fish `s2.1-pro-free`, voice
   “历史故事·清晰”, `reference_id: 6fc59d2b56cf402eb572934114c8d8aa`.
   Set a local `bgm_path` either way.

The provider contract is intentionally split: one project uses one keyframe provider (Codex or
Liblib), Liblib/Kling owns image-to-video, and Fish Audio owns narration.

6. **Assemble.** `python3 scripts/assemble.py out/<project>`
   ffmpeg: normalize + concat all shots, lay narration ducked under the music, burn captions,
   add the watermark. Narration defaults to `continuous` timing: the next sentence starts about
   0.1s after the previous one ends, and visual cuts/captions move to those handoffs instead of
   waiting for a fixed shot slot. Set `narration_timing.mode: "beat_locked"` only when deliberate
   pauses between beats are required. Output `out/<project>/final.mp4`.

7. **Verify.** You can't read an mp4 directly — extract frames to jpg and look:
   `ffmpeg -ss <t> -i final.mp4 -vf "scale=640:-1,format=yuvj420p" -frames:v 1 f.jpg`

### Cadence — how long shots should be

A common mistake is one long shot per beat. On a 9:16 / social piece especially, a static
10s shot reads as dead air. Aim for a **cut every ~4–6 seconds**:

- **Shots run 3–6s; never let a single shot exceed ~7s** — beyond that the AI motion has
  nowhere to go and it feels static.
- **A beat's narration is ~8–10s, so give each beat 2 shots** (a *wide* establishing shot with
  the headline + a *detail* cut-in without it). The narration plays continuously across both;
  the visual cuts mid-sentence. This is the single biggest rhythm win.
- So a ~60s film is typically **~6 beats × 2 shots × ~5s = 12 shots**, not 6 × 10s.
- Reuse the wide keyframe as shot `a`; generate a tighter detail scene for shot `b`.
  `keyframes.py` skips any shot that already has a `keyframe_url`, so adding `b` shots and
  re-running only generates the new ones.

Add a `shots` array to each beat (see schema). Give each shot its own short `scene` and
`motion`; set `"title": true` only on the wide shot so the headline shows once per beat.

## A-roll mode (talking-head → collage)

The default Liblib direct endpoint does not provide video-to-video restyling. Do not run the
legacy A-roll scripts with the default provider; first configure an API-enabled Liblib custom
`video_workflow` whose documented inputs accept the source video.

The standard workflow above is **B-roll**: a topic becomes AI-generated collage posters
that get animated. **A-roll is the reverse case** — the user already has a real recorded
talking-head video (a presenter speaking to camera) and wants it *itself* turned into the
collage look, keeping their actual performance (face, lip movement, gestures) intact. There
is no poster to generate; the "keyframe" is the presenter's own footage. Use A-roll when the
user gives you a video file of themselves/a presenter talking, not a topic to write from
scratch.

1. **Transcribe + auto-segment.** `python3 scripts/asr_beats.py <project_dir> <source.mp4>`
   Runs xai/stt-v1 on the source's own audio and cuts it into beats at sentence-ending
   punctuation or natural pause gaps (never exceeding ~9.5s, under Omni/Kling video-edit's
   10s per-call cap). Writes `beats.json` with each beat's `start`/`end`/`text` — **this is
   the same mandatory approval gate as the B-roll beat map**: review it, set `"theme"` (run
   `style_bakeoff.py` the same way — the presenter's segment works fine as the bake-off
   source), and optionally fill in a `content_beats` string per beat (a sticker/stamp idea
   to layer in) before generating anything.

2. **Generate.** `python3 scripts/aroll_clips.py <project_dir> [only_ids]`
   Cuts each beat's time range out of the source, uploads it, and re-styles it with a
   **photographic paper-cutout sticker** treatment on the presenter — her real likeness,
   lip movement, eye-line and gestures follow the source frame-for-frame; only the
   silhouette edge and the world around her are paper-collage. Default model is
   `google/gemini-omni-flash/video-edit`; any beat it rejects automatically retries on
   `bytedance/seedance-2.0/reference-to-video` (set via `video_model`/`video_model_fallback`
   in beats.json). **Never ask the model to redraw or halftone-texture the face itself** —
   that gets rejected regardless of how the prompt is worded (tried both a strong and a
   softened phrasing; both failed). Uses the same aspect-routing confirm gate as `clips.py`.

3. **Assemble.** `python3 scripts/aroll_assemble.py <project_dir>`
   Muxes each generated clip with the *original* beat segment's own audio (never whatever
   audio the video model produced) so lip-sync is guaranteed regardless of which model
   handled that beat, normalizes every beat to one canvas, and concats into `final.mp4`.

## C-roll mode (one photo → collage)

C-roll uses Codex GPT Image 2 editing with a local anchor image; it does not use Liblib image
generation. Liblib is first used after the edited poster exists, when Kling animates it.
This is the one exception to the non-Codex B-roll routing rule: outside Codex, stop and request
a configured Liblib reference-image workflow instead of silently degrading identity/product fidelity.

The third input modality — "cutout roll". A-roll re-styles a talking-head VIDEO; B-roll
generates everything from a topic; **C-roll takes a single still PHOTO** (a selfie, an
avatar card, a product shot) and anchors it inside the collage world: the subject is cut
out as a PHOTOGRAPHIC sticker — never redrawn — and per-beat posters are generated around
it with an image-EDIT model, then animated through the normal clip stage. Use C-roll when
the user gives you one photo and a topic: a personal explainer fronted by their own face,
or a collage ad built around a real product shot (validated on both, 2026-07-17).

1. **Beat map.** Same as B-roll (`references/beat-layer.md`, same approval gate), plus the
   C-roll fields in beats.json: `"mode": "croll"`, `"anchor_photo"`, `"croll_subject"`
   (`portrait` | `product`), and `subject_wardrobe` (portrait — lock the outfit or the
   paper-doll body drifts) or `subject_desc` (product). Set `"title": false` on shots —
   C-roll posters carry no headline; text belongs to captions. If there is no separate
   script, transcribe/derive narration first and let the audio's ASR timestamps define the
   beats (audio-first, like A-roll — not text-first like B-roll).

2. **Anchored keyframes.** `python3 scripts/croll_keyframes.py <project_dir>`
   Writes `gpt-image-2-edit-manifest.json`. Use Codex image editing with the listed local
   `reference_images`, save each result at `dest`, and rerun the script to register it. Portraits get a
   photographic face + illustrated paper-doll body; products get a pixel-faithful sticker
   with label typography intact. Prompt rules that are baked in (all three cost a re-run to
   learn): poses/expressions go to the BODY only — asking for a wink redraws the face;
   halftone must be scoped to the background or it bleeds onto skin; portrait clothing must
   be locked explicitly. The script also writes `anchor_freeze` into beats.json.

3. **Animate + audio + assemble.** Standard `clips.py` → `audio.py` → `assemble.py`.
   `clips.py` injects the `anchor_freeze` guard into every motion prompt — without it the
   video stage can re-letter a product label (observed: "PARFUM" → "PAREUM") or re-time a
   face. For narration in the subject's own voice, set `voice.clone_ref` (see Voice + music
   above); derive stamp/snap-zoom timing from the narration's ASR word timestamps
   (`asr_beats.py` works on any audio, not just A-roll footage).

## beats.json schema

```json
{
  "project": "my-film", "topic": "...", "language": "en",
  "aspect": "9:16",                       // 16:9 | 9:16 | 1:1 | 3:4
  "style": "collage",
  "image_provider": "auto",            // auto: Codex chat in Codex, otherwise all Liblib
  "image_provider_config": {
    "quality": "medium",
    "max_concurrency": 2
  },
  "image_fallback_provider": "liblib",  // any Codex network failure: regenerate the whole batch
  "image_fallback_model": "liblib-ultra",
  "image_fallback_provider_config": {    // optional; defaults to video_provider_config
    "image_steps": 30,
    "image_max_retries": 1
  },
  "video_provider": "liblib",
  "video_provider_config": {            // keys remain in environment, never JSON
    "kling_model": "kling-v2-1",
    "prompt_magic": 0,
    "video_mode": "std",
    "video_sound": "off"                  // custom/v2.6 workflows only; omitted for v2.1
  },
  "theme": "american-retro",              // THEME_PRESET (styles.THEME_PRESETS) — the LOOK layer
  "arc": "timeline",                      // narrative arc (beat-layer.md) — the STORY skeleton
  "video_model": "liblib-i2v",
  "image_model": "gpt-image-2",
  "image_quality": "medium",              // low | medium | high (API mode)
  "video_resolution": "720p",             // 720p (default); Seedance also 480p/1080p (Omni is 720p-only)
  "motion_style": "punchy",               // amplitude: calm | punchy | max (theme sets a default)
  "constraints": "strict",                // strict = defect guards on | loose = let AI explore + re-roll
  "bgm_path": "/absolute/path/to/bgm.mp3", // Liblib does not provide TTS/BGM; provide local audio
  "mix": {"music": 0.6, "voice": 1.25},   // audio balance — optional; these are the defaults (BGM ducks under the VO)
  "voice": {                             // optional TTS; omit to use beat narration_audio files
    "provider": "fish",
    "model": "s2.1-pro-free",
    "reference_id": "6fc59d2b56cf402eb572934114c8d8aa", // default: 历史故事·清晰
    "speed": 1.0,
    "temperature": 0.65,
    "top_p": 0.7,
    "trim_silence": true                  // remove only TTS file-edge silence, not internal pauses
  },
  "narration_timing": {                  // optional; these are the defaults
    "mode": "continuous",               // continuous | beat_locked
    "gap_s": 0.1,                        // sentence-to-sentence gap in continuous mode
    "lead_in_s": 0.12,                   // short opening breath before sentence one
    "tail_s": 0.5                        // minimum natural finish after the final sentence
  },
  "caption_style": "white",               // white (default: clean white subtitle) | paper (cream cut-out collage look)
  "captions": true,                       // false = no burned-in captions (deliver clean, subtitle in post)
  "watermark": "AI generated",
  "mode": "croll",                        // C-roll only — plus the four fields below
  "anchor_photo": "path/to/photo.png",    // C-roll: the still to anchor (person or product)
  "croll_subject": "portrait",            // C-roll: portrait | product
  "subject_wardrobe": "a cream knitted sweater and charcoal trousers",  // C-roll portrait: outfit lock
  "subject_desc": "the perfume bottle",   // C-roll product: short noun phrase for the sticker
  "beats": [
    {
      "id": 1, "title_cn": "", "title_en": "BEFORE MONEY",
      "bg": "earthy clay tan", "feel": "ancient, humble", "hook": "surprising_stat",
      "narration": "For most of history, there was no money...",
      "shots": [
        // shot_size: EST_WIDE|WIDE|MEDIUM|CLOSE|DETAIL ; camera_move: static|push_in|
        // pull_out|pan|tilt|parallax (flat-safe only) — VARY per adjacent beat, static for payoff
        {"id": "a", "dur": 5, "title": true,  "shot_size": "WIDE", "camera_move": "push_in",
         "scene": "...wide establishing collage...",
         "element_motion": "traders gesture, goat bobs, a paper bird flaps across the frame, coins scatter"},
        {"id": "b", "dur": 5, "title": false, "shot_size": "CLOSE", "camera_move": "parallax",
         "scene": "...close cut-in detail...",
         "element_motion": "the exchanged goods slide together, halftone pulses"}
      ]
    }
  ]
}
```
`theme`+`arc` set the two big layers; `element_motion` per shot is the energy (make it rich — see
below). `motion`/`collage_style`/`era` are still read for back-compat.

## Model selection (always verify IDs live)

The defaults split still-image and motion generation:

| Job | Model | Note |
|---|---|---|
| Keyframe / collage poster | Codex GPT Image 2 or Liblib | Codex uses one parallel subagent per image; any service failure reroutes the whole batch to Liblib. Non-Codex uses Liblib from the start. |
| Animate | Kling image-to-video | `/api/generate/video/kling/img2video` |
| Narration / music | local files | set `narration_audio` per beat and `bgm_path`; not a Liblib workflow API feature |

In Codex, use Liblib fallback through `scripts/keyframe_fallback.py --all` after any Codex
batch network/service failure. Outside Codex, `keyframes.py` uses Liblib directly. `scripts/provider.py` handles Liblib image generation, video submission and local keyframe upload;
`scripts/openai_image.py` handles optional unattended GPT Image 2 API generation.

## Advanced: element-level motion collage

The standard path animates the *whole* poster (great, automated, "living poster"). For the
dramatic **pieces-fly-in-and-assemble** motion collage (à la cr7v2), or to animate **real
people with full control and zero content filters**, cut each poster into independent
elements and drive them with the local keyframe engine (no video model needed).

Read `references/local-engine.md`. In short: `extract_elements.py` (crop + background-removal
+ residue/erase cleanup) → `motion.py` (Layer + keyframes, `fly_in`/`slap`/`drop`/`pop_settle`
easings, procedural confetti/starburst, camera zoom+shake+whip, frame render). Pieces fly
back to their **original positions** on a blurred-placeholder backdrop, so the assembled
frame reconstructs the original poster.

## Editions

- **Workflow edition** (this skill): Codex-or-Liblib batch keyframes, Liblib/Kling motion, Fish voice.
- **Manual prompt-pack**: if the user does not have Liblib API access, just produce the beat map + the per-beat
  image prompts + the per-clip motion prompts + the narration script for them to paste into
  any generator. The creative engine (the prompts) is identical.

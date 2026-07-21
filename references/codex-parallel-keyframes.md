# Codex parallel keyframe protocol

Read this whenever a Codex image manifest contains more than one item.

## Root-agent procedure

1. Load the complete manifest and count `items` as `N`.
2. Request exactly `N` logical subagents, one for each image. Start every available worker
   immediately. If the runtime concurrency cap is below `N`, keep the extra one-image tasks
   pending and refill each slot as soon as a worker finishes; never move those tasks back to
   sequential image generation in the root agent.
3. Give each worker only its manifest item, model/aspect, exact destination, and reference
   images when present. Do not let workers edit `beats.json` or either manifest.
4. Monitor all workers. On the first network/service failure, interrupt workers that are still
   generating and run `python3 scripts/keyframe_fallback.py <project> --all`. Ignore completed
   Codex files so one finished video never mixes providers.
5. Treat a content/quality rejection differently: stop for creative review instead of changing
   providers automatically.
6. After every worker succeeds, verify that every `dest` exists and is a non-empty PNG, then
   rerun the script that produced the manifest to normalize/register paths.

## Worker contract

Each image worker must:

- own exactly one manifest item;
- invoke `$imagegen` exactly once (continuing the same running call is not a retry);
- use `reference_images` for edit manifests;
- copy the generated file to the exact absolute `dest`;
- report `{key, status, dest, error_type}` to the root;
- write no other project files.

Use short task names derived from the key, such as `keyframe_2a`. Sharing the project filesystem
is intentional; unique destinations prevent write conflicts.

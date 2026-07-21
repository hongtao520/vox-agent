#!/usr/bin/env python3
"""Codex manifest metadata for one-subagent-per-image execution."""
from __future__ import annotations


def execution_contract(item_count: int, *, edit: bool = False) -> dict:
    """Describe the agent orchestration contract consumed by Codex, not Python."""
    return {
        "strategy": "one_subagent_per_image",
        "requested_subagents": int(item_count),
        "max_images_per_subagent": 1,
        "operation": "image_edit" if edit else "image_generation",
        "start_policy": "spawn_all_immediately",
        "capacity_policy": (
            "If the runtime agent limit is lower than requested_subagents, queue the remaining "
            "one-image tasks and refill every free slot immediately. The root agent must not "
            "generate manifest images sequentially itself."
        ),
        "worker_write_scope": "Write only the assigned dest PNG; never edit beats.json or manifests.",
        "success_policy": "The root agent validates all dest files, then reruns the manifest producer.",
        "network_failure_policy": (
            "On the first network/service failure, interrupt unfinished image workers and run the "
            "whole-project Liblib fallback. Do not retry Codex."
        ),
        "content_failure_policy": "Stop for creative review; do not silently change providers.",
    }


def instruction(item_count: int, *, producer: str, edit: bool = False) -> str:
    operation = "edit" if edit else "generate"
    return (
        f"Create exactly {item_count} subagents for {item_count} manifest items: one subagent per "
        f"image. Start them in parallel. Each worker must use Codex image generation once to {operation} "
        "only its assigned item, save the PNG at that item's exact dest, and never edit JSON. "
        "If runtime capacity is lower, keep one logical task per image and schedule pending tasks in "
        "waves as slots free; the root must not generate images sequentially. On any network/service "
        "failure, interrupt unfinished workers and use the whole-project Liblib fallback. If all "
        f"succeed, rerun {producer} to register the files."
    )

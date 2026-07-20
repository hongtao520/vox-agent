# Fish Audio voice roster

Use Fish Audio `s2.1-pro-free` for generated narration. The default is the selected
Chinese documentary voice:

```json
{
  "provider": "fish",
  "model": "s2.1-pro-free",
  "name": "历史故事·清晰",
  "reference_id": "6fc59d2b56cf402eb572934114c8d8aa",
  "speed": 1.0,
  "temperature": 0.65,
  "top_p": 0.7,
  "trim_silence": true
}
```

If `voice` is absent (or a legacy voice block has no `provider`) and the beats do not
already contain usable local `narration_audio`, `audio.py` applies this default.

## Curated Chinese alternatives

| Name | Reference ID |
|---|---|
| 纪录片男声·沉稳 | `7d4cc998f68c413ba5605d892d7acc87` |
| 纪录片男声·年长 | `f51dfe8db3524c89a4201aacfa18e56e` |
| 历史故事·清晰 (default) | `6fc59d2b56cf402eb572934114c8d8aa` |
| 温暖磁性旁白 | `4d0e64e39e4b4f31a816f133795c0db5` |
| 叙事旁白·戏剧感 | `6910bc3ba4284e31b49be252faf3601b` |
| 宣传片男声·浑厚 | `36ef842120654ee6b38ef43c8f08535a` |

Generate auditions with:

```bash
python3 scripts/fish_audio.py audition out/voice-auditions --text "同一句试听旁白"
```

For a Fish library voice or an authorized clone, replace only `name` and
`reference_id`. Keep one voice for the complete film.

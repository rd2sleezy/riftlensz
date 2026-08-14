# Clock OCR corpus (H.9.1 real validation)

Labels are **manual visual checks** of League HUD clock crops, cross-checked against
Replay/capture API approximate game time. **H.9.1 OCR output is never used as ground truth.**

- `real/` — REAL in-game clock crops (`source_type=REAL`)
- `real_negative/` — REAL non-clock HUD crops from the same match frames
- `synthetic/` — SYNTHETIC only; **does not count** toward real acceptance

All REAL samples are from match `NA1_5620410094` at frame size **1520×982**
(windowed R.10 capture). 720p / 1080p / 1440p native clients were **not** validated here.

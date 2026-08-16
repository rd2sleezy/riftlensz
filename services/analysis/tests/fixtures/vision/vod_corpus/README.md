# Real VIDEO validation corpus

Media files are **not** stored here. Catalog entries use portable refs:

- `r10://{match_id}/{capture_id}/{filename}` → `~/.riftlens/captures/...`
- `vod://{relative}` → `$RIFTLENS_VOD_ROOT` or `~/.riftlens/vods/...`

Optional uncommitted overlay: `~/.riftlens/vod_corpus/local.yaml` (absolute paths allowed there only).

Kinds:

| Kind | Counts toward H.10 / H.12 real-VOD? |
|---|---|
| `REAL` | yes (user OBS/ShadowPlay/full or partial gameplay VIDEO) |
| `R10-CLIP` | no |
| `REPLAY-GENERATED` | no |
| `SYNTHETIC` | no |

Independent checkpoints live under `checkpoints/`. Labels are visual HUD readings. **Never copy H.10 SyncMap output into those files.**

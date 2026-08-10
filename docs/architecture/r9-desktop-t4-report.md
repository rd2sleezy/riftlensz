# R.9 desktop T4 — NA1_5617764200

**Result:** PASSED  
**Date:** 2026-08-09  
**Tier:** manual Windows T4 (real League client + real `.rofl`)  
**Not CI.** This is committed evidence per the native-replay amendment §14.1.

## Subject

| Field | Value |
|---|---|
| Match | `NA1_5617764200` |
| Review | `01KZMXE3JHJT9PG9H5VR02E1FR` |
| Participant | pid 9 Kaisa BOTTOM LOSS |
| Replay | operator-selected `NA1-5617764200.rofl` (path not hardcoded) |
| Patch | 16.15 |

## Assertions observed

1. Opened the real Kaisa pid 9 review for `NA1_5617764200`.
2. Add Gameplay → Import League Replay selected the real `.rofl`.
3. Import linked the replay **without** launching League.
4. UI showed Replay linked / ready to open.
5. Open Replay launched the actual League replay.
6. RiftLens connected successfully (READY only after backend confirmation).
7. Coaching timestamp click controlled the real League replay via R.8 `reveal`.
8. First tested reveal landed approximately **0.6 s** from the expected R.6 target — within the **≤1000 ms** real landing tolerance.
9. Multiple timestamps across the review sought successfully.
10. Close Replay kept the source attached.
11. After restarting RiftLens: `.rofl` remained linked; the previous live session was **not** treated as still open.
12. Open Replay established a **new** session; timestamp reveal worked again.

## Out of scope

A coaching-quality defect found during this demo is **not** an R.9 replay failure. Recorded separately:

`docs/follow-ups/post-fight-actionable-state.md`

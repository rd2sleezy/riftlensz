# R.10.5 overlay T4 — NA1_5617764200

**Result:** PASSED (v1 acceptance)  
**Date:** 2026-08-11  
**Tier:** manual Windows T4 (real League client + real `.rofl`)  
**Not CI.** Committed evidence for the replay coaching overlay companion.

Further overlay polish is **post-v1**. This report closes R.10.5.

## Subject

| Field | Value |
|---|---|
| Match | `NA1_5617764200` |
| Display mode used | Borderless (v1 path) |
| Latest fix included | `58fc5126778e5f89b246836baf081a0a8d35d148` |

## Assertions observed

1. Access Overlay launcher appeared during an active READY replay session.
2. Clicking Access Overlay opened the expanded navigator + detail overlay.
3. Expanded overlay remained open indefinitely (no hover/inactivity collapse).
4. Mouse movement away from the overlay did not hide it.
5. League receiving OS focus did not collapse the overlay.
6. Issue navigator (Focus / Secondary / Strengths) was usable and scrollable.
7. Clicking a finding row sought the real League replay via the existing R.8/R.9 reveal path.
8. Navigator / detail layout was satisfactory for v1.
9. Minimize returned explicitly to Access Overlay; restore worked.
10. No unwanted automatic collapse remained after the sticky-presentation fix.
11. HUD placement was acceptable (minimap / bottom HUD / timeline usable).
12. League Esc / Space / replay controls remained usable with the overlay open.
13. Borderless workflow is the accepted v1 path.

## Known limitation (documented, not a T4 failure)

True exclusive Direct3D fullscreen cannot composite an external Electron always-on-top overlay. RiftLens does not inject into League or rewrite `game.cfg` WindowMode. Player path: Borderless or Windowed, then Recheck. This is accepted for v1.

## Out of scope / post-v1

- Automatic exclusive-fullscreen → Borderless switching
- Additional overlay visual polish
- R.11 / H.10 / CV / clip analysis

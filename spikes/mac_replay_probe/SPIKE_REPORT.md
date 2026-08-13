# Mac `.rofl` Replay Feasibility Spike — Report

**Branch:** `integrate/ui-r1`  
**Replay:** `NA1-5620410094.rofl`  
**Spike path:** `spikes/mac_replay_probe/` (throwaway; no production integration)

## Verdict

### `MAC_REPLAY_SUPPORTED`

A real `.rofl` opened on macOS, entered `GAMESTATE_GAMELOOP`, exposed `/replay/playback` after enabling the Replay API in the **game-read** config, and successfully supported:

- reading the replay clock (`length` / `time`)
- pause (time stopped)
- play (time advanced)
- seek to early / mid / late timestamps (fresh GET verified each landing)

---

## Config edit (approved)

| Item | Path |
|------|------|
| **Backup (LoL/Config)** | `spikes/mac_replay_probe/backups/game.cfg.bak-20260812-212501` |
| **Backup (Game/Config)** | `spikes/mac_replay_probe/backups/game.GameConfig.cfg.bak-20260812-213206` |
| Edit 1 | `/Applications/League of Legends.app/Contents/LoL/Config/game.cfg` → `EnableReplayApi=1` under `[General]` |
| Edit 2 (required) | `/Applications/League of Legends.app/Contents/LoL/Game/Config/game.cfg` → `EnableReplayApi=1` under `[General]` |

Minimal diffs: one line each (`EnableReplayApi=1` after `EnableAudio=1`), CRLF preserved, all other settings unchanged.

**Critical finding:** Editing only `…/LoL/Config/game.cfg` left `/replay/*` absent. The Mac game client with `-GameBaseDir=…/Game` reads **`…/Game/Config/game.cfg`**. Both were set for this run; Game/Config was the enabling change.

---

## Deliverables

### 1. Mac League install / application path

| Item | Path |
|------|------|
| App bundle | `/Applications/League of Legends.app` |
| LoL root | `…/Contents/LoL` |
| Game dir | `…/Contents/LoL/Game` |
| Game binary | `…/Game/LeagueofLegends.app/Contents/MacOS/LeagueofLegends` |
| Config (user/UI) | `…/LoL/Config/game.cfg` |
| Config (game-read for this launch) | `…/LoL/Game/Config/game.cfg` |

### 2. Replay path used

`/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl`  
(RIOT magic, NA1 / 5620410094, ~19.3 MB)

### 3. Replay launch method

Direct exe (file association still fails):

```text
LeagueofLegends \
  "<rofl>" \
  -GameBaseDir=/Applications/League of Legends.app/Contents/LoL/Game \
  -Region=NA -PlatformID=NA1 -Locale=en_US -SkipBuild
```

`cwd` = Game dir. Wrong `GameBaseDir=…/LoL` → wad missing / soft-repair.

### 4. Visibly launched / GAMELOOP

**Yes.** stderr: `Replay filepath: …NA1-5620410094.rofl` and `GAMESTATE_SPAWN → GAMESTATE_GAMELOOP`.

### 5. Port 2999

**Yes** (~8s after launch). TLS via Node + pinned `riotgames.pem` (not `verify=False`).

### 6. OpenAPI `/replay/playback`

**Yes** once Game/Config had `EnableReplayApi=1` and the session loaded (~3s after port up).

Documented replay paths included:

`/replay/playback`, `/replay/game`, `/replay/render`, `/replay/recording`, `/replay/banners`, `/replay/particles`, `/replay/sequence`

### 7. Pause / play

| Step | Result |
|------|--------|
| GET playback | `length≈2484.3`, `time` readable, `paused=false` |
| POST `{paused:true}` | `paused=true`; time stable across 1.5s samples |
| POST `{paused:false}` | `paused=false`; time advanced ≥1s over ~2.5s |

### 8. Seek

| Target (s) | GET `time` | Land (±3s) |
|------------|------------|------------|
| 30 (early) | 30 | yes |
| ~1117.9 (mid) | ~1117.9 | yes |
| ~2111.7 (late) | ~2111.7 | yes |

### 9. Optional endpoints

| Endpoint | Status |
|----------|--------|
| `/replay/game` | 200 — e.g. `processID` |
| `/replay/render` | 200 — camera/render fields |
| `/replay/recording` | 200 — recording metadata |
| `/liveclientdata/gamestats` | 200 |
| `/liveclientdata/eventdata` | 200 |

### 10. Exact failures (still true / historical)

- `open <rofl>` → `kLSApplicationNotFoundErr`
- `GameBaseDir=…/LoL` → `ALE-18967991` missing `Bootstrap.macos.wad.client`
- LoL/Config-only `EnableReplayApi=1` → OpenAPI without `/replay/*`, GET `/replay/playback` → 404 `Invalid URI format`
- Stock macOS Python SSL vs Riot CA → `Missing Authority Key Identifier` (use Node agent / same pattern as Windows TLS helper)

### 11. Final verdict

**`MAC_REPLAY_SUPPORTED`**

### 12. Is `MacReplayHost` feasible?

**Yes**, as a follow-on production work unit (not started here).

Reuse: Replay API client, TLS CA pin, session/seek, ClockMap.

Mac-specific: install locator, **`GameBaseDir=…/Game`**, enable/ensure `EnableReplayApi=1` in **`Game/Config/game.cfg`** (and likely keep LoL/Config in sync), process lifecycle without Windows APIs, no `.rofl` Finder association.

### 13. Production work next (needs separate approval)

1. Implement `MacReplayHost` behind `ReplayHostPort` without weakening `WindowsReplayHost`.
2. Consent-gated `game.cfg` enablement for **Game/Config** (and document dual paths).
3. Only then consider ungating macOS `.rofl` import in the UI.
4. Do **not** start H.10 / R.12 / V.5 without explicit approval.

---

## Prior vs this run

| Run | Config | `/replay/playback` | Control |
|-----|--------|--------------------|---------|
| Earlier spike | flag absent | 404 | n/a → `MAC_REPLAY_PARTIAL` |
| After LoL/Config only | LoL/Config=1 | 404 for 2+ min in GAMELOOP | fail |
| After Game/Config=1 | both=1 | 200 | pause/play/seek pass → **`MAC_REPLAY_SUPPORTED`** |

---

## Stop — waiting for approval

No `MacReplayHost`, no production UI import enablement, no coaching/UI changes beyond this spike folder.

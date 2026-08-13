# Mac `.rofl` Replay Feasibility Spike — Report

**Branch:** `integrate/ui-r1`  
**Replay:** `NA1-5620410094.rofl`  
**Date:** 2026-08-13  
**Spike path:** `spikes/mac_replay_probe/` (throwaway; no production integration)

## Verdict

### `MAC_REPLAY_PARTIAL`

A real `.rofl` **opens and enters gameplay** on macOS. Port **2999** listens with **Riot-CA TLS**. **Live Client Data** works. The **Replay API** (`/replay/playback` and pause/play/seek) is **not exposed** in this environment.

`EnableReplayApi` is **absent** from `game.cfg`. Per spike rules it was **not** written. Until that flag is approved and retested, RiftLens-style clock control is **not proven**.

---

## Deliverables (1–13)

### 1. Mac League install / application path

| Item | Path |
|------|------|
| App bundle | `/Applications/League of Legends.app` |
| LoL root | `/Applications/League of Legends.app/Contents/LoL` |
| Game dir (DATA lives here) | `…/Contents/LoL/Game` |
| Game binary | `…/Game/LeagueofLegends.app/Contents/MacOS/LeagueofLegends` |
| Config | `…/Contents/LoL/Config/game.cfg` |
| Bootstrap wad | `…/Game/DATA/FINAL/Bootstrap.macos.wad.client` (present) |

`EnableReplayApi` in `[General]`: **not present** (not edited).

### 2. Replay path used

`/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl`  
(~19.3 MB, magic `RIOT`, identity **NA1** / **5620410094**)

### 3. Replay launch methods attempted

| Method | Result |
|--------|--------|
| `open <file.rofl>` (Finder association) | **Fail** — `kLSApplicationNotFoundErr` (no app claims `.rofl`) |
| Direct exe with `-GameBaseDir=…/LoL` (Windows-analog) | **Fail** — `ALE-18967991` WadFile mount failed: `DATA/FINAL/Bootstrap.macos.wad.client` Missing; writes `SOFT_REPAIR` |
| Direct exe with `-GameBaseDir=…/LoL/Game`, `cwd=Game` | **Success** — loads replay, GAMELOOP, listens on 2999 |

Working launch (spike only):

```text
LeagueofLegends \
  "<rofl>" \
  -GameBaseDir=/Applications/League of Legends.app/Contents/LoL/Game \
  -Region=NA -PlatformID=NA1 -Locale=en_US -SkipBuild
```

### 4. Whether the replay visibly launched

**Yes.** Logs show `Replay filepath`, loading screen → `GAMESTATE_GAMELOOP`, render init. LeagueofLegends process stayed alive for minutes during probing.

### 5. Whether port 2999 became reachable

**Yes** (within ~5–10s of successful launch).

### 6. Whether OpenAPI exposed `/replay/playback`

**No.**

- `GET https://127.0.0.1:2999/swagger/v3/openapi.json` → **200**, title `LoLClient`
- Documented surface: async helpers + **`/liveclientdata/*`** + swagger meta
- **No** `/replay/*` paths
- `GET /replay/playback` → **404** `RESOURCE_NOT_FOUND` / `Invalid URI format`

TLS: Node `https` + pinned `riotgames.pem` + loopback identity skip (**not** `verify=False`) **works**. Stock macOS Python 3.13 `ssl` failed with `Missing Authority Key Identifier`.

### 7. Pause / play result

**Not tested successfully** — `/replay/playback` unavailable (404). No pause/play control path.

### 8. Seek result

**Not tested successfully** — same reason.

### 9. Optional endpoint availability

| Endpoint | Result |
|----------|--------|
| `/replay/game` | 404 / not in OpenAPI |
| `/replay/render` | 404 / not in OpenAPI |
| `/replay/recording` | 404 / not in OpenAPI |
| `/liveclientdata/gamestats` | **200** — e.g. `gameMode=CLASSIC`, `gameTime≈10`, `mapName=Map11` |
| `/liveclientdata/eventdata` | **200** — events present |
| `/liveclientdata/allgamedata` | **200** — spectator note: activePlayer unsupported |

### 10. Exact failures / errors

- `open` → `LSOpenURLsWithCompletionHandler() failed … kLSApplicationNotFoundErr`
- Wrong `GameBaseDir` → `ALE-18967991 FATAL ERROR - Installation is corrupt. WadFile mount failed … Bootstrap.macos.wad.client … Missing`
- `/replay/playback` → HTTP 404 `Invalid URI format`
- LCU remoting warnings while detached from client (non-fatal for local replay): `LCURemotingClient: Unable to connect to app process`
- Python urllib TLS vs Riot CA: `CERTIFICATE_VERIFY_FAILED: Missing Authority Key Identifier`

### 11. Final verdict

**`MAC_REPLAY_PARTIAL`**

### 12. Does a proper `MacReplayHost` appear feasible?

**Conditionally feasible for launch; control unknown.**

- Platform-neutral Replay API client / TLS / seek / ClockMap can likely be reused **if** `/replay/playback` appears after `EnableReplayApi=1`.
- Mac-specific host would need: install locator, `GameBaseDir=…/Game` (not LoL root), no `.rofl` file association, process lifecycle without Windows APIs.
- **Do not** ship `MacReplayHost` until pause/play/seek are proven against a real replay.

### 13. Production work next (only if control is proven after config approval)

1. **Approval required:** set `EnableReplayApi=1` under `[General]` in `game.cfg` (spike will not write it).
2. Re-run this spike’s control suite (pause / play / seek with GET verification).
3. If supported → implement `MacReplayHost` behind existing `ReplayHostPort`; keep Windows host untouched; keep UI macOS import gated until green.
4. If still no `/replay/*` → treat as `MAC_REPLAY_UNSUPPORTED` for RiftLens control (Live Client alone is insufficient for seek).

---

## Architecture note (read-only)

| Layer | Platform |
|-------|----------|
| Replay API HTTP client, TLS CA pin, session/seek, ClockMap | Neutral (reuse) |
| Install locator, `game.cfg` EnableReplayApi, process launch | Windows today; Mac needs different paths/args |
| `UnsupportedReplayHost` / `nativeReplaySupported === win32` | Intentionally unchanged |

---

## Stop — waiting for approval

No production UI/import changes. No H.10 / R.12 / V.5.

**Need your OK to:** write `EnableReplayApi=1` into `game.cfg` and re-run pause/play/seek on the same `.rofl`.

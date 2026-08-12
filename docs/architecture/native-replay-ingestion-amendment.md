# RiftLens Native Replay Ingestion Amendment

**Document type:** Technical architecture amendment
**Amends:** H.4 (persistence), H.8 (review association), H.9 (desktop video attachment)
**Does not modify:** H.1, H.2, H.3, H.5, H.6, H.7 behaviour
**New work order series:** R.0 – R.11 (interleaved with, not replacing, H.10+)
**Author role:** System architect. Implementation is performed by Cursor from the work orders in §15.

---

## 0. Executive summary

RiftLens can support native `.rofl` ingestion, but **not** by parsing replay contents. The correct architecture treats a `.rofl` as an *opaque, launchable artifact* whose only supported interface is the League game client itself, via Riot's documented **Replay API** on `https://127.0.0.1:2999`.

The load-bearing facts this design rests on:

1. Riot documents a Replay API with `GET/POST /replay/playback` (read and set paused state, current time, speed, length), `GET/POST /replay/render`, `GET/POST /replay/recording`, `GET/POST /replay/sequence`, and `GET /replay/game`.
2. The Replay API is **disabled by default** and is enabled by adding `[General]` / `EnableReplayApi=1` to `<install>/Config/game.cfg`. Once enabled, the game client generates Swagger v2 / OpenAPI v3 specs at `127.0.0.1:2999` — which is the canonical way to *detect* that the API is usable.
3. The game client serves HTTPS with a self-signed certificate; Riot publishes the root certificate for validation.
4. The Live Client Data API (`/liveclientdata/*`) is served from the same port and process, giving `gamestats.gameTime`, an `eventdata` event list with `EventTime`, and a `playerlist` with per-champion level/items/scores/isDead.
5. `.rofl` files are conventionally named `PLATFORM-gameId.rofl` (e.g. `NA1-4567890123.rofl`) and contain a JSON metadata section at the head of the file.
6. Replays are patch-locked: an old `.rofl` will not play on a newer client build.
7. The League Client (LCU) API is explicitly documented by Riot as **not officially supported for third-party use**, with no guarantees of documentation, uptime, or change communication.

Everything else — packet payloads, positional data, chunk/keyframe decoding — is out of scope and stays out of scope.

**The single most important consequence:** RiftLens does not need to render or store video to satisfy the click-to-replay requirement. `POST /replay/playback {"time": <seconds>, "paused": false}` *is* the seek primitive. H.9's SyncMap becomes one of several `ClockMap` implementations rather than the only mechanism.

**The second most important consequence:** the design must be honest about what is *documented* versus *assumed*. The LCU launch path, the exact behaviour of Live Client Data endpoints inside a replay, and the relationship between `playback.time` and MATCH-V5 `t_ms` are **hypotheses**. R.0 (§16) exists solely to convert those hypotheses into recorded facts before a single line of production code is written.

---

## 1. Feasibility

### 1.A — Information safely available from the `.rofl` file without rendering

Available, low-risk, cheap:

| Item | Source | Reliability |
|---|---|---|
| Platform ID + game ID | **Filename** (`NA1-4567890123.rofl`) | High — but user-renameable |
| File magic / signature prefix | First bytes of file | High for "is this a rofl at all" |
| Game version / patch string | Head JSON metadata block | Medium — layout has shifted historically |
| Game length (ms) | Head JSON metadata block | Medium |
| Per-participant end-of-game summary (champion, KDA, CS, items) | Embedded stats JSON | Medium |
| File size, mtime, SHA-256 | Filesystem | High |

**Architectural rule:** identity resolution is a *strategy chain*, ordered by robustness, not a parser.

```
1. Filename convention  ->  (platformId, gameId)          [preferred]
2. Head metadata JSON   ->  (gameVersion, gameLength, gameId)
3. LCU replay metadata  ->  (gameId -> metadata)          [best effort, unsupported API]
4. User disambiguation  ->  "Which match is this?" picker [always available]
```

If step 1 succeeds, steps 2–3 are *enrichment*, not requirements. If step 2 fails, RiftLens degrades to "patch unknown — attempt launch and let the client decide", **not** to failure. The parser must therefore be a bounded, defensive, best-effort reader: read at most the first N KB, never seek based on untrusted offsets without bounds-checking, never treat a parse failure as fatal.

**Do not build a `.rofl` parser that anything depends on.** Build a `.rofl` *sniffer* whose every output is `Optional`.

### 1.B — Information available through Riot MATCH-V5 / timeline (H.2/H.3)

This remains, unchanged, the **analysis source of truth**:

- Full participant roster, champions, runes, summoner spells, teams, roles.
- Per-frame (≈60s) participant state: position, current gold, total gold, XP, level, CS, jungle CS, damage stats.
- Discrete events with ms timestamps: kills (with victim/killer/assists/position/bounty), building kills, elite monster kills, ward placed/killed, item purchase/sell/undo/destroy, level up, skill level up, turret plate destroyed, champion special kill, game end.
- Derived by H.3: lane resolution, map zones, position interpolation.

**Nothing in this amendment changes this.** GST is populated from Riot data only. The replay is a *rendering and navigation surface* over an analysis that already exists.

### 1.C — Information available through League replay/client APIs

Documented Replay API (`127.0.0.1:2999`, requires `EnableReplayApi=1`):

| Endpoint | Gives RiftLens |
|---|---|
| `GET /replay/game` | Game client process info — used as an "is a replay actually up" liveness probe |
| `GET /replay/playback` | **Current replay time, total length, paused state, seeking state, speed** |
| `POST /replay/playback` | **Seek, play/pause, speed** — the entire click-to-replay primitive |
| `GET/POST /replay/render` | Camera position/rotation/mode, fog of war, and other render properties |
| `GET/POST /replay/recording` | **Start a recording for a codec + output path; poll for progress** — the frame-capture primitive (§7) |
| `GET/POST /replay/sequence` | Keyframe sequences (camera choreography) — not needed for MVP |
| `GET /swagger/v3/openapi.json` | **Capability detection** — presence of replay paths proves the API is enabled |

Live Client Data API (same port, same process):

| Endpoint | Gives RiftLens |
|---|---|
| `/liveclientdata/gamestats` | `gameTime`, `gameMode`, `mapName` — **independent clock cross-check** |
| `/liveclientdata/eventdata` | Event list with `EventTime` — **clock calibration anchors** (§5) |
| `/liveclientdata/playerlist` | Per-champion level, items, scores, `isDead`, `respawnTimer`, position *role* |
| `/liveclientdata/activeplayer` | Full active-player stats — **assume unavailable in a spectator replay** |

Undocumented / unsupported (LCU on the lockfile port):

- Replay folder path, replay metadata by gameId, "watch this replay" trigger, current patch state, gameflow phase.
- Riot states plainly that this service is not officially supported for third-party applications and carries no uptime or change guarantees.

**Architectural rule:** the LCU may be used, but only behind a `LeagueClientPort` that is (a) optional, (b) individually feature-probed, and (c) never the only path to any user-visible capability.

### 1.D — Information that still requires reading rendered frames

Genuinely unavailable from A/B/C, and therefore the eventual justification for computer vision (§8):

- Sub-frame champion positions between MATCH-V5's ~60s frames (interpolation is an estimate, not an observation).
- Actual current HP/mana bars for non-active champions.
- Fog-of-war state *as the player saw it* — what was actually visible on screen.
- Ability casts, skillshot trajectories, dodges, flashes, animation cancels.
- Camera position and player attention proxies.
- Minimap glance-ability: what information was on screen at the moment of a decision.
- Pings, chat, summoner-spell cooldown HUD, item actives.
- Wave state and minion positions.

None of this is required for the MVP. It is required for RiftLens to eventually say *"you had no vision here and your camera was bottom-side"* rather than *"you died here"*.

### 1.E — Things we must NOT depend on

Explicitly forbidden as dependencies:

1. **Decoding `.rofl` chunk/keyframe payloads.** Undocumented, encrypted in practice, changes across patches. Any tool that once did this is a liability, not a reference.
2. **Spectator-server emulation** (standing up a fake `/observer-mode/rest/consumer` endpoint to feed the client). Historically used by community projects; brittle, patch-fragile, and semantically closer to impersonating Riot infrastructure than to reading a file.
3. **Memory reading, DLL injection, overlays, or input synthesis into the game process.** Anti-cheat and Riot policy risk. Non-negotiable: RiftLens never writes to the game process.
4. **Historical community `.rofl` parsers as authorities.** They may inform the sniffer's *hypotheses*; they may never be the reason a code path is assumed to work.
5. **Screen-scraping via OS capture APIs as the primary capture mechanism.** `POST /replay/recording` is the sanctioned path and it targets a file. OS capture is a distant fallback, not a design.
6. **Assuming `activeplayer` exists in a replay.** Treat as absent until R.0 proves otherwise.

**Feasibility verdict:** see Appendix A.

---

## 2. Replay source architecture

### 2.1 Naming

`ReplaySource` is the wrong name because an MP4 is not a replay. The abstraction is: *a thing that can show the user the moment a Finding refers to*.

**`GameplaySource`** is the root concept. Two implementations at launch:

```
GameplaySource
├── VideoGameplaySource     (H.9 — MP4/H.264 + ffprobe + manual SyncMap)   [cross-platform]
└── RoflGameplaySource      (new — .rofl + League client + Replay API)     [Windows-only]
    └── (future) RemoteRoflGameplaySource  (same, hosted on another machine)
```

### 2.2 Capability model, not interface inheritance

Sources differ in what they can do, not only in how they do it. Encoding that as method presence produces `NotImplementedError` sprawl. Encode it as data:

```python
class SourceCapability(Enum):
    SEEK              = "seek"
    PLAY_PAUSE        = "play_pause"
    SPEED_CONTROL     = "speed_control"
    AUTOMATIC_CLOCK   = "automatic_clock"      # ROFL: yes. Video: no.
    MANUAL_CLOCK      = "manual_clock"         # Video: yes. ROFL: yes (as override).
    FRAME_CAPTURE     = "frame_capture"        # ROFL: yes (R.10). Video: later.
    CAMERA_CONTROL    = "camera_control"       # ROFL only.
    INLINE_RENDER     = "inline_render"        # Video: yes (in-app <video>). ROFL: no (external window).
```

The UI renders from capabilities. It never branches on `source_type` except for copy strings and icons. This is what keeps Windows/ROFL assumptions from leaking (§9).

### 2.3 Ports

Five small ports. Each is independently testable and independently faked.

**`GameplaySourceDescriptor`** — pure value object, no I/O, persisted.
```
source_id, match_id, source_type, source_uri, content_hash,
capabilities: set[SourceCapability],
platform_scope: PlatformScope,   # ANY | WINDOWS
status: SourceStatus,
detail: VideoDetail | RoflDetail
```

**`PlaybackController`** — the transport. The only thing the review UI calls.
```
open() -> PlaybackSession
close()
state() -> PlaybackState(position_ms, duration_ms, paused, seeking, speed, healthy)
seek(position_ms, *, then: PlayIntent) -> SeekOutcome
set_paused(bool)
set_speed(float)
```
`position_ms` is always in **source time**, never game time. Translation is the `ClockMap`'s job, and only the orchestrator does it. This is the boundary that stops "which clock is this number in?" bugs.

**`ClockMap`** — bidirectional, total, explicit about confidence. Generalises H.9's SyncMap.
```
to_source_ms(game_t_ms) -> int
to_game_ms(source_ms) -> int
confidence: ClockConfidence   # EXACT | CALIBRATED | ESTIMATED | MANUAL | UNKNOWN
method: str                   # "identity", "manual_offset", "event_anchor_v1", ...
domain: (game_min_ms, game_max_ms)
```
Implementations: `IdentityClockMap`, `LinearOffsetClockMap` (H.9's SyncMap, unchanged semantics), `CalibratedReplayClockMap` (offset + anchors + residual).

**`FrameCaptureProvider`** — optional capability, added in R.10.
```
capture(interval: CaptureRequest) -> CaptureHandle
poll(handle) -> CaptureProgress
cancel(handle)
```

**`GameplaySourceFactory`** — resolves a persisted descriptor into a live controller on the current platform, or returns a typed `Unavailable` reason. On macOS, a ROFL descriptor resolves to `Unavailable(PLATFORM_UNSUPPORTED)`; it does not raise, and the review still opens.

### 2.4 What the rest of the pipeline sees

Nothing. H.5/H.6/H.7/H.8 have no knowledge of gameplay sources. The only consumer is:

```
Review UI  ->  GameplaySourceService.reveal(finding)  ->  clamp + lead-in + ClockMap + PlaybackController
```

`reveal(finding)` is the *entire* public surface for click-to-replay, and it is identical for MP4 and ROFL. That is the design's success criterion.

---

## 3. ROFL import pipeline

### 3.1 Stages

```
[1] SELECT        user picks game.rofl (or drops it)
     |
[2] VALIDATE      path safety, size bounds, magic bytes                  -> ROFL_UNREADABLE / ROFL_NOT_RECOGNISED
     |
[3] IDENTIFY      filename -> (platformId, gameId); head JSON -> patch   -> MATCH_ID_UNRESOLVED
     |
[4] CORRELATE     resolve to an existing RiftLens match (H.2/H.4)        -> MATCH_NOT_INGESTED
     |            if absent: offer "ingest this match first" (runs H.2)
[5] ENVIRONMENT   locate League install; read/patch game.cfg;
     |            probe openapi.json for replay paths                    -> LEAGUE_NOT_FOUND / REPLAY_API_DISABLED
[6] COMPAT        declared replay patch vs installed patch               -> PATCH_INCOMPATIBLE (warn, allow override)
     |
[7] SAFETY        refuse if a live game / queue is active                -> LIVE_GAME_IN_PROGRESS
     |
[8] LAUNCH        launch strategy chain (§4.2)                           -> LAUNCH_REJECTED / LAUNCH_TIMEOUT
     |
[9] CONNECT       poll 2999 until /replay/playback responds              -> REPLAY_API_UNREACHABLE
     |
[10] CALIBRATE    establish ClockMap (§5)                                -> CLOCK_CALIBRATION_FAILED (degrade to manual)
     |
[11] BIND         persist replay_session + clock_map, mark source READY
     |
[12] REVIEW       user reviews; click-to-replay live
```

Stages 1–4 are **cross-platform and pure enough to unit test on macOS**. Stages 5–11 are Windows-only. That split is the seam in §9.

### 3.2 Failure states — the canonical taxonomy

One enum, used by Python, IPC, DB, and UI. Every failure carries `code`, `user_message`, `technical_detail`, `recoverable`, `suggested_action`.

| Code | Meaning | Recoverable | Suggested action |
|---|---|---|---|
| `PLATFORM_UNSUPPORTED` | Not Windows | No | Attach a video instead |
| `ROFL_UNREADABLE` | I/O error, permissions, zero bytes | Maybe | Re-select file |
| `ROFL_NOT_RECOGNISED` | Magic bytes absent | No | File is not a League replay |
| `ROFL_METADATA_UNPARSED` | Head JSON unreadable | **Yes — non-fatal** | Continue with unknown patch |
| `MATCH_ID_UNRESOLVED` | No gameId from any strategy | Yes | Ask user to pick the match |
| `MATCH_NOT_INGESTED` | gameId not in RiftLens DB | Yes | Offer to ingest via H.2 |
| `LEAGUE_NOT_FOUND` | No valid install root | Yes | Let user browse to install |
| `REPLAY_API_DISABLED` | `game.cfg` lacks flag / openapi lacks replay paths | Yes | Offer one-click enable + restart client |
| `LIVE_GAME_IN_PROGRESS` | Gameflow not idle | Yes | Ask user to finish their game |
| `PATCH_INCOMPATIBLE` | Replay patch ≠ installed patch | Yes (override) | Explain; allow "try anyway" |
| `LAUNCH_REJECTED` | Process exited immediately / client refused | Yes | Retry, then fallback strategy |
| `LAUNCH_TIMEOUT` | No Replay API within N seconds | Yes | Retry with longer timeout |
| `REPLAY_API_UNREACHABLE` | Port 2999 refuses / TLS fails | Yes | Diagnose cert + firewall |
| `PLAYBACK_NOT_ADVANCING` | Unpaused, but `time` static | Yes | Reconnect |
| `SEEK_FAILED` | Target not reached within tolerance | Yes | Retry once, then report |
| `CLOCK_CALIBRATION_FAILED` | Anchors unmatched | **Yes — degrade** | Fall back to manual offset |
| `SESSION_LOST` | Replay window closed | Yes | Offer relaunch |

**Hard rule:** `SourceStatus` never reads `READY` unless stage 9 succeeded in the current session. A `.rofl` sitting on disk is `LINKED`, not `READY`. This is the mechanism that makes §11's "never silently claim success" structurally true rather than a matter of discipline.

---

## 4. League client / replay control

### 4.1 The adapter boundary

```
        RiftLens core (cross-platform, pure)
                    |
          [ ReplayHostPort ]  <-- the ONLY seam Windows code crosses
                    |
   +----------------+------------------+
   |                                   |
WindowsReplayHost              UnsupportedReplayHost
(R.2–R.6)                      (macOS/Linux — returns typed Unavailable)
   |
   +-- LeagueInstallLocator      (registry, well-known paths, user override)
   +-- GameConfigManager         (read/patch game.cfg, backup, verify)
   +-- LeagueClientPort (LCU)    (optional, feature-probed, never load-bearing)
   +-- ReplayApiClient           (2999, TLS-pinned, typed)
   +-- LiveClientDataClient      (2999, typed, optional endpoints)
   +-- ReplayProcessSupervisor   (launch strategies, liveness, teardown)
```

`ReplayHostPort` is a **coarse** port — roughly a dozen methods, session-oriented, all returning `Result[T, ReplayError]`. It is deliberately coarse so it can later be hosted out-of-process behind a transport without a chatty protocol (§9).

### 4.2 Concrete responsibilities

**Enabling the Replay API.**
`<install>/Config/game.cfg` must contain `[General]` with `EnableReplayApi=1`. RiftLens must: read the file, detect whether the flag is present and correct, back the file up (`game.cfg.riftlens.bak`) before writing, write minimally (preserve all other keys and sections), and then **verify by probing `https://127.0.0.1:2999/swagger/v3/openapi.json` for `/replay/playback`** rather than trusting the write. Editing requires the game to be restarted; the UI must say so. RiftLens must never edit `game.cfg` without an explicit user click.

**Locating the install.** Strategy chain: user-configured path → Windows registry (Riot Games / uninstall keys) → well-known paths (`C:\Riot Games\League of Legends`, `C:\Program Files\Riot Games\...`) → LCU `install-dir` if the client is running → user browse dialog. Validate a candidate by structure (presence of `Config/`, `Game/`, and the game executable) — never by name alone.

**Launching the replay.** Strategy chain, tried in order, each independently probed and recorded:
1. **LCU watch** — if the client is running and the LCU replay endpoints answer, ask the client to play the replay by gameId. Requires the file to be resolvable in the client's replay folder (stage the file there via copy if needed, then clean up). Undocumented API → strategy, not requirement.
2. **Shell-open the `.rofl`** — invoke the OS file association, which is how double-clicking works. Simple, robust, but gives no return channel.
3. **User-assisted** — RiftLens tells the user "open this replay in your client", then waits for the Replay API to come up. Ugly, but it *always works*, and it means the feature degrades to inconvenient rather than broken.

R.0's job includes deciding, empirically, which of 1/2 is primary. Strategy 3 ships regardless as the terminal fallback.

**Detecting successful playback.** Not "the process started". The definition of started is:
`GET /replay/playback` returns 200 **and** `length > 0` **and**, after unpausing, `time` advances monotonically across two samples ≥1s apart. Anything less is `LAUNCH_TIMEOUT` or `PLAYBACK_NOT_ADVANCING`.

**Playback control.** `POST /replay/playback` with any subset of `{paused, time, speed}`. RiftLens issues *intent* and then *verifies*; it never assumes a POST took effect. Every control operation is: POST → poll until `seeking == false` and state matches within tolerance → timeout → typed error.

**Camera behaviour.** MVP: **do not touch `/replay/render`.** Leave the camera in the user's control. Camera manipulation is a §7/R.10 concern (deterministic framing for capture) and a possible later "focus my champion" feature. Touching the camera in the MVP adds a large surface of patch-fragile render properties for no coaching value.

**Lifecycle.** `IDLE → LAUNCHING → CONNECTING → READY → (SEEKING ⇄ PLAYING ⇄ PAUSED) → CLOSING → CLOSED`, plus `FAILED(code)` reachable from any state. One state machine, one place, fully unit-testable with a fake clock and a fake transport.

**Reconnect / retry.** Two distinct policies:
- *Transient* (connection refused during startup, single 5xx): bounded exponential backoff, capped total wait, silent.
- *Session loss* (replay window closed by the user, process gone): **do not auto-relaunch.** Transition to `FAILED(SESSION_LOST)` and surface a "Replay closed — reopen?" affordance. Auto-relaunching a game client the user just closed is hostile.

Never retry a seek more than once. Never poll faster than ~4 Hz. Never poll at all when the review UI is not visible.

---

## 5. Game time synchronization

### 5.1 The problem, stated precisely

GST uses `t_ms`: milliseconds from Riot's match start. The Replay API's `playback.time` is seconds in the replay's own timeline. These are *probably* the same origin, offset by a small constant covering loading and pre-minion time. **"Probably" is not a foundation.** So RiftLens measures the offset instead of assuming it.

```
source_ms = game_t_ms - offset_ms          (rate assumed 1.0 — replays don't drift)
game_t_ms = source_ms + offset_ms
```

### 5.2 Calibration ladder

Attempted in order; each rung records its own confidence. The result is a `CalibratedReplayClockMap` that is honest about how it was derived.

**Rung 0 — Identity (`ESTIMATED`).** Assume `offset_ms = 0`. Sanity-gate it: `|playback.length*1000 − match.gameDuration_ms| ≤ 5000`. If the durations disagree badly, do not proceed to review with a silent identity map.

**Rung 1 — Duration anchor (`ESTIMATED`).** If lengths differ by a consistent amount, that difference is a candidate offset. Weak, but better than nothing.

**Rung 2 — Event anchoring (`CALIBRATED`) — the primary method.** This is the good one:

1. Seek to a few probe points across the match (e.g. 25%, 50%, 75% of length), pausing at each.
2. At each point, read `GET /liveclientdata/eventdata`, which returns events with `EventTime` in seconds — including champion kills.
3. Take MATCH-V5 timeline kill events (which RiftLens already has in GST with ms timestamps) and match them to Live Client Data kill events by **ordinal sequence and victim/killer champion**, not by time.
4. For each matched pair, `offset_i = riot_t_ms − (EventTime_i × 1000)`.
5. Require **≥3 matched anchors** with **standard deviation ≤ 750 ms**. Take the median as `offset_ms`. Record `residual_ms` (max absolute deviation) as the calibration quality metric.

This is robust because it never trusts a single number, it self-validates (a bad match produces high variance and is rejected), and it uses two independent data sources that RiftLens already holds.

**Rung 3 — Cross-check (`CALIBRATED`, verification only).** `GET /liveclientdata/gamestats` returns `gameTime`. While paused at a known `playback.time`, compare. If `gamestats.gameTime` tracks `playback.time` closely, the offset is confirmed from a second angle; if it tracks *game clock* instead, it is itself a direct offset measurement. R.0 determines which. Either outcome is useful.

**Rung 4 — Manual (`MANUAL`).** User nudges: "this moment in the replay is 18:42 in my game." Produces a `LinearOffsetClockMap`. Always overrides any automatic result and is sticky per source.

### 5.3 Should manual sync survive?

**Yes, in three roles, and it is not optional:**

1. **Required** for `VideoGameplaySource`. H.9's behaviour is untouched.
2. **Fallback** for ROFL when calibration fails — the difference between "feature broken" and "feature slightly annoying".
3. **Override** for ROFL when calibration succeeds but the user disagrees. The user is allowed to be right.

The UI must always show which regime is active: *Auto-synced (±0.3s)* / *Estimated* / *Manual*. Never present an estimated clock with the confidence styling of a calibrated one.

### 5.4 Rules that prevent clock bugs

- `ClockMap` is immutable. Recalibration produces a new object and a new DB row; it never mutates.
- Only `GameplaySourceService` converts between clocks. `PlaybackController` speaks source time exclusively. UI speaks game time exclusively.
- Every persisted timestamp records its domain in the column name: `game_t_ms` vs `source_ms`. No bare `time` columns.
- Calibration runs once per session, not per seek.

---

## 6. Click-to-replay

### 6.1 Behaviour specification

Trigger: user clicks the timestamp on a Finding at `game_t_ms = 1_122_000` (18:42).

```
 1. lead_in_ms = finding.lead_in_ms ?? rule_default ?? 8000      # H.9 semantics preserved
 2. target_game_ms = clamp(1_122_000 - 8_000, 0, match_duration_ms)   -> 1_114_000  (18:34)
 3. if source.status != READY:
        -> ROFL: offer "Open replay" (launch flow), remember pending reveal, return
        -> VIDEO: existing H.9 path
 4. target_source_ms = clock_map.to_source_ms(target_game_ms)
 5. POST /replay/playback {"paused": true}
 6. POST /replay/playback {"time": target_source_ms / 1000}
 7. poll GET /replay/playback @4Hz, ≤5s, until seeking == false
        and |time*1000 - target_source_ms| <= 500ms
        else -> SEEK_FAILED (retry once, then surface, do NOT silently play)
 8. POST /replay/playback {"paused": false, "speed": 1.0}
 9. verify advancement within 1.5s -> else PLAYBACK_NOT_ADVANCING
10. UI: mark the finding as "playing", show a countdown to the event moment,
        show the ±residual if confidence < CALIBRATED
```

### 6.2 Preserved from H.9

- Lead-in is a **per-rule** property. A "you facechecked" finding wants 8s; a "you back-timed badly" finding wants 25s. H.7 rules already carry evidence; lead-in defaults live with the rule pack, and this amendment does not change any rule.
- Clamping at match boundaries.
- Clicking a second finding while playing = new reveal, not queued.
- Findings without a timestamp are not clickable.

### 6.3 New for ROFL

- **Focus, don't fight the user.** RiftLens does not force the League window to the foreground on every seek in the MVP (it may offer a "bring replay forward" button). Stealing focus mid-review is worse than one extra alt-tab.
- **Pause before seek, always.** Seeking while playing produces non-deterministic landings.
- **Reveal is cancellable.** A seek in flight is abortable by a new reveal.

---

## 7. Frame capture

### 7.1 The primitive

Riot's `POST /replay/recording` starts a recording given a codec and an output filepath; subsequent `GET /replay/recording` calls report progress. This is exactly `capture_interval(start, end)` and it means **RiftLens never renders or stores a full-match MP4.**

```python
CaptureRequest(
    source_id,
    start_game_ms = 1_110_000,     # 18:30
    end_game_ms   = 1_135_000,     # 18:55
    mode          = CaptureMode.SAMPLED,
    fps           = 2,
    max_artifacts = 60,
)
```

### 7.2 Modes

| Mode | Output | Use |
|---|---|---|
| `STILL` | 1–3 images at exact game timestamps | "What did the minimap look like at the moment of death" |
| `SAMPLED` | N images/sec over the interval | CV over a window; cheapest useful CV input |
| `CLIP` | One short video for the interval | User-facing "share this mistake" |

`STILL` is implemented as degenerate `SAMPLED`, not as a separate code path.

### 7.3 Hard constraints

- **Capture is not real-time.** The client renders the interval; wall-clock cost may exceed interval duration substantially. Every capture is async, cancellable, and progress-reporting. Never block the UI thread. Never capture on the click-to-replay path.
- **Capture is never implicit.** Only an explicit user action or an explicitly-enabled rule may request it. Silently writing gigabytes of PNGs is unacceptable.
- **Budgeted.** Per-review caps: total captured seconds, total artifact count, total bytes. Refuse past the cap with a typed error, don't degrade silently.
- **Camera determinism (deferred).** Reproducible CV eventually needs a known camera. That is `/replay/render` work, and it is explicitly out of MVP scope; R.10 captures whatever the user's camera shows and records that fact in provenance.

### 7.4 Storage and cleanup

```
%LOCALAPPDATA%\RiftLens\captures\{match_id}\{capture_interval_id}\
    frame_000123_g1110500.png
    manifest.json          # request, resolved game_t_ms per frame, clock_map_id, patch, sha256s
```

Every artifact carries `game_t_ms` in its filename **and** the manifest. Retention classes: `EPHEMERAL` (deleted at session end), `REVIEW` (lives with the review, GC'd when the review is deleted), `PINNED` (user kept it). Cleanup runs at: capture completion (partials), session teardown, app startup GC, and on a size ceiling with LRU eviction. Deleting a review cascades to its artifacts. Staged `.rofl` copies are cleaned on the same schedule.

---

## 8. Computer vision integration

**Not in the MVP.** What matters now is that the seams exist so CV can be added later without redesigning provenance.

### 8.1 The contract

```
CaptureInterval -> MediaArtifact[] -> Detector -> FrameObservation[] -> Evidence -> Rule -> Finding
```

```python
@dataclass(frozen=True)
class FrameObservation:
    observation_id: str
    match_id: str
    gameplay_source_id: str
    capture_interval_id: str
    media_artifact_id: str
    game_t_ms: int              # via ClockMap, with the clock_map_id recorded
    clock_map_id: str
    observation_type: str       # "minimap_vision_state", "hp_fraction_observed", ...
    payload: dict
    confidence: float           # detector confidence, 0..1
    detector_id: str
    detector_version: str
    provenance: Provenance = Provenance.VISUAL
```

### 8.2 Provenance is the load-bearing requirement

Extend the existing evidence provenance enum:

```
Provenance.RIOT_TIMELINE     # H.2/H.3 — authoritative, deterministic
Provenance.DERIVED_METRIC    # H.5 — deterministic function of the above
Provenance.VISUAL            # NEW — observed, probabilistic, source-dependent
```

Three non-negotiable rules:

1. **Visual observations never enter GST.** GST stays a Riot-derived, deterministic, reproducible structure. `FrameObservation` is a *parallel stream* keyed by `game_t_ms`, joined at query time. This preserves §17 exactly: a review computed today and recomputed next year from the same Riot data produces the same GST.
2. **Findings carry mixed provenance explicitly.** An `EvidenceBundle` (H.8) may contain both kinds; the UI labels visual evidence distinctly ("observed from replay footage") and shows detector confidence. A user must always be able to tell which claims are facts and which are inferences from pixels.
3. **Visual rules degrade, they don't fail.** H.6 already has required-input handling and suppression. Rules gain `requires_visual: true`; without observations they are suppressed exactly like any other missing-input rule. A review on a machine with no replay capability is a *smaller* review, never a broken one.

### 8.3 Sequencing

CV rules ship in their own `V.x` series, after R.10 and after a real corpus of captured intervals exists. Nothing in R.0–R.11 depends on CV existing.

---

## 9. Windows worker architecture

### 9.1 The options

**A — Run RiftLens itself on Windows for replay work.**
+ Zero transport, zero serialisation, zero clock skew, zero file transfer. Files are local. Debugging is direct.
+ Matches how real users will actually run it — the League player and the replay are on the same machine, always.
− Developer must build/test on Windows for this subsystem.
− macOS build must degrade gracefully (it must anyway).

**B — Windows Replay Worker + cross-platform RiftLens.**
+ Nice dev loop on macOS; conceptually elegant.
− Requires: a transport, auth, service discovery, versioning, error mapping across a boundary, and — fatally — **the `.rofl`, the League install, and every captured artifact live on the Windows box while the UI and DB live on the Mac.** Every capture becomes a file transfer. Every path becomes ambiguous.
− Doubles the failure surface at exactly the moment we are trying to establish whether the underlying Replay API works at all.

**C — Hybrid: A's topology, B's seam.**

### 9.2 Recommendation: **C**

Ship **A** — RiftLens Desktop running on Windows owns replay analysis end to end, in-process, no network protocol — but implement it **behind the coarse `ReplayHostPort` from §4.1**, so that hosting it out-of-process later is a transport addition rather than a refactor.

Concretely, for the MVP:

- All replay code lives in `riftlens/replay_host/` with a `windows/` subpackage. Nothing outside `replay_host` imports `winreg`, references drive letters, or assumes a League install.
- `ReplayHostFactory` returns `WindowsReplayHost` on `sys.platform == "win32"` and `UnsupportedReplayHost` elsewhere. macOS development, tests, packaging, and the full video path continue to work with zero conditionals in the UI.
- The port is **coarse and session-oriented** (`open_session`, `reveal(game_t_ms, lead_in_ms)`, `get_state`, `capture_interval`, `close_session`) — roughly 12 methods — precisely so it survives being moved across a process boundary later without becoming chatty.
- Everything in stages 1–4 of §3.1 (validation, identification, correlation) is cross-platform and unit-testable on macOS.

**The developer workflow this implies:** the Mac remains the primary dev machine for ~80% of the work (domain, persistence, UI, clock math, state machines, all of T0–T2 testing). The Windows PC is used for R.0 and for the T3/T4 test tiers, driven by a standalone CLI (§16) that runs there directly. That CLI *is* the future worker's entrypoint if B is ever needed — so the work is not throwaway.

**Defer B to R.12+**, gated on real demand (e.g. users with a headless League box). Do not build it now.

---

## 10. Security and safety

**Process launching.**
- Never elevate. If a path requires admin, fail with a clear message.
- Resolve the executable only from a *validated* install root; verify the structure, canonicalise the path, reject symlinks/junctions/UNC paths/relative traversal, and confirm the resolved binary is inside the install root after canonicalisation.
- Never interpolate user-supplied strings into a command line. Use argument arrays, never a shell.
- Bound the child: track the PID, detect immediate exit, and never leave orphans on RiftLens shutdown.

**Local ports and APIs.**
- RiftLens is a **client only**. It binds nothing and listens on nothing for the MVP. (If B is ever built, its listener binds loopback by default and requires an explicit, token-authenticated opt-in for LAN.)
- Connect only to `127.0.0.1:2999` and the LCU port, never to a hostname, never to `0.0.0.0`.
- **Validate TLS against Riot's published root certificate** rather than disabling verification. Ship the pinned cert; do not use `verify=False`. If pinning fails, that is a real, reportable error.
- Treat 2999 responses as untrusted input: schema-validate, bound sizes, never `eval`.

**Replay API exposure.** Enabling `EnableReplayApi=1` opens a local API on the user's machine. Therefore: only edit `game.cfg` on explicit consent, explain in plain language what the flag does, back up the file, and offer a one-click revert. Never enable it silently.

**Path validation.** `.rofl` inputs: canonicalise, require a regular file, enforce size bounds (reject absurdly small and absurdly large), reject anything that isn't a real file. Never construct output paths by concatenating user strings; capture output paths are RiftLens-generated under RiftLens-owned directories only.

**Malicious or invalid files.** A `.rofl` is untrusted data. The sniffer reads a bounded prefix, bounds-checks every offset before seeking, caps the metadata JSON size, and uses a strict JSON parser. A malformed file must produce a typed error, never an unbounded read or a crash. RiftLens never executes the file — it asks the League client to open it.

**Credentials.** The LCU lockfile password is read at point of use, held in memory only, never logged, never persisted, and redacted from all error messages and telemetry. Riot API keys remain in H.2's existing handling — unchanged, and never near replay code.

**Avoiding interference with live games.** Before any launch: check that no live game is in progress (LCU gameflow phase, and/or a live-game probe on 2999). If a game or queue is active, refuse with `LIVE_GAME_IN_PROGRESS`. RiftLens must never launch a replay over someone's ranked game, and must never send input to the game process under any circumstance.

**Policy.** Riot's developer policy prohibits products that surface in-game information conferring competitive advantage. RiftLens is post-game coaching over completed matches — squarely fine — but the boundary must stay explicit: **no live-game overlays, no real-time advice, no reading a game in progress.** Riot also requires third-party products to display the standard non-endorsement notice; this belongs in the About screen.

---

## 11. Patch compatibility

### 11.1 Detection

Two independent signals:

- **Declared replay patch** — from the head metadata JSON (optional; may be absent).
- **Installed client patch** — from LCU patch state if available, else from install metadata, else unknown.

Compare at **major.minor** granularity only. Never require an exact build match; never hard-block on a comparison whose inputs may be missing.

```
compare(replay_patch, installed_patch) ->
    LIKELY_COMPATIBLE   | same major.minor
    LIKELY_INCOMPATIBLE | replay older than installed
    UNKNOWN             | either side missing
```

**The client is the authority, not RiftLens.** The compatibility check produces a *prediction*, and a wrong prediction must never be the reason a working replay is blocked. `LIKELY_INCOMPATIBLE` warns and offers "Try anyway". `UNKNOWN` proceeds silently and lets the launch outcome speak.

### 11.2 User messaging

| State | Message | Actions |
|---|---|---|
| Compatible | "Replay ready — patch 15.14." | Open replay |
| Incompatible | "This replay is from patch 15.9, but League is on 15.14. Riot replays usually stop working after a patch, so this probably won't open." | Try anyway · Attach video instead |
| Unknown patch | "Couldn't read this replay's patch. We'll try to open it and let you know." | Open replay |
| League not found | "Couldn't find your League installation." | Browse… · Attach video instead |
| Replay API disabled | "League needs one setting enabled for RiftLens to control replays. We'll add `EnableReplayApi=1` to your game config and back up the original. You'll need to restart League." | Enable and show me · Cancel |
| Corrupted replay | "This file doesn't look like a League replay." | Choose another file |
| Launch failure | "League didn't open the replay. Your coaching review is still complete — it's built from Riot match data, not the replay." | Retry · Attach video · Continue without replay |

### 11.3 The non-negotiable invariant

> **RiftLens must never present replay-backed navigation as working when the replay did not render.**

Structurally enforced, not by discipline:

1. `SourceStatus` cannot be `READY` without a live, verified session (§3.2).
2. The review header shows replay state at all times; there is no state in which the UI is silent about it.
3. Finding timestamps are only clickable-as-replay when a `READY` session exists; otherwise they render as inert text with a "Open replay to jump here" affordance.
4. A failed launch is a **first-class visible outcome** with an error code and a retry, never a swallowed exception.
5. **Analysis success and replay success are reported separately.** A review is complete and valid without any gameplay source at all — because it always was. Replay is navigation, not analysis.


## 12. Database changes

All changes are **additive**. No existing H.4 table is dropped or repurposed. New tables use the existing repository-port pattern: a port in the domain layer, a SQLAlchemy implementation in the adapter layer, an Alembic revision per work order.

### 12.1 New tables

**`gameplay_source`** — replaces the implicit "attached VOD" concept with an explicit one.
```
id                TEXT PK
match_id          TEXT FK -> match(id)  NOT NULL
source_type       TEXT NOT NULL         -- 'video' | 'rofl'
source_uri        TEXT NOT NULL         -- absolute path
content_hash      TEXT NULL             -- sha256 (video: partial; rofl: full)
display_name      TEXT NULL
status            TEXT NOT NULL         -- 'linked'|'ready'|'unavailable'|'error'
platform_scope    TEXT NOT NULL         -- 'any' | 'windows'
last_error_code   TEXT NULL
last_verified_at  TIMESTAMP NULL
created_at        TIMESTAMP NOT NULL
UNIQUE(match_id, source_uri)
```
`status` is a **cached hint** for UI, never a source of truth for "can I seek right now". Liveness is always established by a live session.

**`rofl_source_detail`** — 1:1 with `gameplay_source` where `source_type='rofl'`.
```
gameplay_source_id  TEXT PK FK
platform_id         TEXT NULL      -- 'NA1'
game_id             BIGINT NULL
declared_patch      TEXT NULL
declared_length_ms  INTEGER NULL
identify_method     TEXT NOT NULL  -- 'filename'|'header'|'lcu'|'user'
header_parse_status TEXT NOT NULL  -- 'ok'|'partial'|'failed'|'skipped'
raw_metadata_json   TEXT NULL      -- capped size; diagnostics only
```

**`clock_map`** — generalises H.9's SyncMap. Append-only; never updated in place.
```
id                  TEXT PK
gameplay_source_id  TEXT FK NOT NULL
kind                TEXT NOT NULL   -- 'identity'|'linear_offset'|'calibrated_replay'
offset_ms           INTEGER NOT NULL DEFAULT 0
rate                REAL NOT NULL DEFAULT 1.0
confidence          TEXT NOT NULL   -- 'exact'|'calibrated'|'estimated'|'manual'|'unknown'
method              TEXT NOT NULL   -- 'event_anchor_v1'|'manual'|...
anchor_count        INTEGER NULL
residual_ms         INTEGER NULL
is_active           BOOLEAN NOT NULL
created_at          TIMESTAMP NOT NULL
```
Exactly one `is_active` row per source (enforced in the repository).

**`replay_session`** — the audit trail that makes §11's invariant provable.
```
id, gameplay_source_id FK, started_at, ended_at,
outcome            TEXT   -- 'ready'|'failed'|'closed'
failure_code       TEXT NULL
launch_strategy    TEXT NULL   -- 'lcu_watch'|'shell_open'|'user_assisted'
observed_patch     TEXT NULL
observed_length_ms INTEGER NULL
api_probe_json     TEXT NULL   -- which endpoints answered (capability record)
```

**`capture_interval`** (R.10)
```
id, gameplay_source_id FK, clock_map_id FK,
start_game_ms, end_game_ms, mode, fps, requested_by,
status  -- 'requested'|'running'|'complete'|'failed'|'cancelled'
error_code NULL, requested_at, completed_at, artifact_count, total_bytes
```

**`media_artifact`** (R.10)
```
id, capture_interval_id FK, kind ('image'|'clip'), path, sha256, bytes,
frame_index, game_t_ms, retention_class ('ephemeral'|'review'|'pinned'), expires_at
```

**`frame_observation`** — schema sketched here, **created in the V.x series, not in R.x.**

### 12.2 Migration of existing H.9 attachments

One Alembic revision:
1. Create `gameplay_source`, `rofl_source_detail`, `clock_map`, `replay_session`.
2. Backfill: every existing video attachment → a `gameplay_source` row with `source_type='video'`, `platform_scope='any'`, `status='linked'`.
3. Backfill: every existing SyncMap → a `clock_map` row with `kind='linear_offset'`, `confidence='manual'`, `is_active=true`.
4. **Leave the original H.9 tables in place and readable** for one release. The H.9 repository is reimplemented as a thin shim over the new tables so existing UI code paths keep working unchanged; the old tables are dropped only in a later, separate revision after the shim is proven.

Downgrade path must be tested. Backfill must be idempotent.

---

## 13. UI changes

**Scope discipline: only the gameplay-source surface changes.** Focus items, secondary items, strengths, metrics panels, and evidence rendering are untouched.

### 13.1 `Attach VOD` → `Add Gameplay`

```
[ Add Gameplay ▾ ]
  ├─ Import League Replay (.rofl)      ← Windows only; on macOS: disabled + "Available on Windows"
  └─ Attach Video (.mp4)               ← unchanged H.9 path
```
The macOS state is *explained*, not hidden. A greyed item with a reason teaches; a missing item confuses.

### 13.2 Import wizard

Linear, one concern per step, every step failable and retryable:
`Choose file → Validating → Matched to <match> → Checking League → [Enable Replay API?] → Patch check → Ready`

The wizard ends at **Ready to open**, not at "opened". Launching is a separate, explicit user action from the review screen — because launching a game client is heavyweight and should never be a side effect of importing a file.

### 13.3 Gameplay status bar (review header)

Always visible, one line, one state:

| State | Display |
|---|---|
| None | `No gameplay attached` · [Add Gameplay ▾] |
| Video | `Video · manual sync` · [Adjust sync] |
| ROFL linked | `Replay · patch 15.14` · [Open replay] |
| ROFL incompatible | ⚠ `Replay may not open — patch 15.9 vs 15.14` · [Try anyway] |
| Launching | `Opening replay…` + spinner + elapsed + [Cancel] |
| Ready | ✓ `Replay connected · auto-synced ±0.2s` · [Close] |
| Degraded | ⚠ `Replay connected · sync estimated` · [Set sync manually] |
| Error | ✕ `<plain-language message>` · [Retry] [Attach video instead] |

Rendered from `SourceCapability` + `SourceStatus` + `ClockConfidence`. **No `if source_type == 'rofl'` in view code.**

### 13.4 Click-to-replay in the UI

- `READY` → timestamp is a button; click runs §6.1; button shows a transient "seeking…" then "playing".
- `LINKED` → timestamp shows a subtle "Open replay to jump here" affordance; clicking starts the launch flow and **remembers the pending reveal**, executing it once ready.
- No source → timestamp is inert text (H.9 behaviour).
- Confidence below `CALIBRATED` → a small "±Ns" badge next to the seek target.

### 13.5 Fallback video behaviour

Entirely unchanged. A match may have both a video and a replay source; the user picks the active one, and the choice is remembered per match. Video remains the only inline-rendering source (`INLINE_RENDER` capability); ROFL playback is an external window and the UI says so.

---

## 14. Testing

Five tiers. **Tiers T0–T2 run in CI on macOS/Linux with no League client.**

**T0 — Pure unit (fast, cross-platform, every commit).**
Clock math and round-tripping; anchor-matching algorithm against synthetic event sets (including deliberately ambiguous and adversarial ones); lead-in and clamping; the session state machine driven by a fake clock; error taxonomy completeness (every code has a user message); path validation (traversal, symlink, UNC, non-file); `.rofl` sniffer against checked-in fixtures — valid header, truncated, empty, wrong magic, oversized metadata, hostile offsets; repository CRUD against in-memory SQLite; Alembic upgrade→downgrade→upgrade with backfill idempotence.

**T1 — Adapter contract tests against `FakeReplayApiServer`.**
A **real HTTPS server** (self-signed, on an ephemeral port) implementing the documented `/replay/*` and `/liveclientdata/*` shapes — and their misbehaviours: seek latency, `seeking` staying true, time not advancing, mid-session connection drop, 500s, malformed JSON, slow responses. Verifies real HTTP/TLS/timeout/retry code, not mock call assertions. **Every adapter behaviour in §4 has a T1 test.**

**T2 — Recorded-transcript tests (schema-drift detection).**
R.0 records every real request/response to `fixtures/replay_api/<patch>/session.jsonl`. T2 replays those transcripts against the adapter. A new patch changing a field name fails a CI test instead of surprising a user. Fixtures are regenerated deliberately, per patch, and reviewed as part of the diff.

**T3 — Windows integration (no game launch).**
Runs on Windows; gated, not on every PR. Install location discovery on a real filesystem; `game.cfg` read/patch/backup/restore against real files; registry probing; LCU lockfile discovery and handshake when the client is running; port probing behaviour when nothing is listening.

**T4 — Real replay smoke test (manual/gated, the only tier that proves the product works).**
Operator runs the R.0 probe CLI against a real `.rofl` on a real install. Emits a machine-readable report; passing is defined by assertions, not by an operator's judgement.

### 14.1 Definition of a passing real-replay test

All must hold, and the report must be committed as evidence:

1. Replay reaches `READY` within **120 s** of launch.
2. `GET /replay/playback` returns `length > 0` and `|length×1000 − match.gameDuration_ms| ≤ 5000 ms`.
3. Unpaused playback advances **≥ 0.9 s of replay time per 1.0 s wall-clock** at speed 1.0, over a 10 s sample.
4. Three seeks — early (~15% of length), mid (~50%), late (~85%) — each land within **±1000 ms** of target within **5 s**.
5. A seek issued while playing, after an explicit pause, lands within tolerance (no drift-past).
6. Pause holds: `time` static across a 3 s sample after `paused=true`.
7. Clock calibration produces **≥3 matched anchors** with **residual ≤ 750 ms**.
8. `/liveclientdata/eventdata` and `/liveclientdata/gamestats` respond during the replay; their availability is recorded either way.
9. Clean teardown: session closed, no orphaned processes, `game.cfg` restorable from backup.
10. The report records the League patch, the replay patch, the winning launch strategy, and the full endpoint-capability probe.

**Anything less is a failing test, and R.1+ does not begin until this passes on real hardware.**

---

## 15. Implementation strategy

### 15.1 Insertion into the roadmap

The R-series is a **parallel track**, not a replacement for H.10+. R.0 is a spike with a stop/go gate. R.1–R.2 are pure and can be done on macOS today. Only R.3+ require the Windows machine.

```
H.9 ──┬── H.10, H.11 …  (existing product roadmap, unblocked)
      │
      └── R.0 (PoC gate) ── R.1 ── R.2 ── R.3 ── R.4 ── R.5 ── R.6 ── R.7 ── R.8 ── R.9 ── R.10 ── R.11
                  ▲
          STOP/GO: if R.0 fails, the Replay API approach is dead and this amendment is revised,
          having cost one spike instead of eight work orders.
```

### 15.2 Work orders

---

#### **R.0 — Replay Control Proof of Concept (throwaway spike, Windows)**

**Objective.** Prove, on real hardware with a real `.rofl`, that RiftLens can launch a replay, connect to the Replay API, read game time, pause/play, and seek to a requested timestamp. Fail loudly otherwise.

**Modules/files.** `spikes/replay_probe/` — standalone, outside the RiftLens package tree, single-purpose CLI. Not imported by anything.

**Boundaries.** No RiftLens imports. No DB. No UI. No mocks anywhere. No `verify=False`. Full spec in §16 / Appendix D.

**Tests.** The spike *is* the test. It emits `probe_report.json` and a raw `session.jsonl` transcript.

**Acceptance criteria.** All ten conditions in §14.1 pass on a real machine, and both artifacts are committed to `fixtures/replay_api/<patch>/`.

**Do NOT implement.** Persistence, UI, capture, camera control, macOS support, the abstraction layer, error taxonomy, or anything reusable. This code is expected to be deleted.

---

#### **R.1 — GameplaySource domain (pure, cross-platform)**

**Objective.** Introduce `GameplaySource`, `SourceCapability`, `ClockMap`, `PlaybackState`, and the full `ReplayError` taxonomy as pure domain types with no I/O.

**Modules/files.** `riftlens/domain/gameplay/{source.py,capability.py,clock.py,errors.py,ports.py}`

**Boundaries.** No HTTP, no filesystem, no DB, no platform checks. `ClockMap` implementations are pure functions. Every error code carries a user-facing message.

**Tests.** T0. Clock round-trip property tests across offsets/domains; boundary clamping; error-taxonomy exhaustiveness.

**Acceptance.** `VideoGameplaySource` is expressible in the new model with H.9's exact behaviour; full type coverage; no import of anything outside `domain`.

**Do NOT implement.** Any adapter, any ROFL logic, any DB table, any UI change.

---

#### **R.2 — `.rofl` identification and validation (pure, cross-platform)**

**Objective.** Given a file path, produce a `RoflIdentity` (platformId, gameId, patch, length) via the §1.A strategy chain, safely.

**Modules/files.** `riftlens/rofl/{sniffer.py,identity.py,validation.py}`; fixtures under `tests/fixtures/rofl/`.

**Boundaries.** Read a bounded prefix only. Bounds-check every offset. Cap metadata size. Every field `Optional`. Parse failure is `ROFL_METADATA_UNPARSED`, never an exception, never fatal. **No launching, no LCU, no network.**

**Tests.** T0 against valid, truncated, empty, wrong-magic, oversized-metadata, and hostile-offset fixtures. Fuzz the header with random bytes: must never raise an uncaught exception or read unbounded.

**Acceptance.** Correct identity from a real `.rofl` filename with an unreadable body; no crash on any adversarial fixture; 100% branch coverage on the sniffer.

**Do NOT implement.** Payload parsing of any kind. Patch comparison. Match correlation.

---

#### **R.3 — Windows environment discovery**

**Objective.** Locate the League install, read/patch `game.cfg`, and detect Replay API availability.

**Modules/files.** `riftlens/replay_host/windows/{install_locator.py,game_config.py,capability_probe.py}`

**Boundaries.** Windows-only, entirely inside `replay_host`. Config writes are backed-up, minimal, and consent-gated. Availability is confirmed by probing `openapi.json` for replay paths, never by trusting the write. No launching.

**Tests.** T0 for `game.cfg` parse/patch/preserve/backup against temp files (cross-platform). T3 for real registry/filesystem discovery.

**Acceptance.** Locates a real install; patches a real `game.cfg` preserving all other keys; correctly reports enabled/disabled; leaves a restorable backup.

**Do NOT implement.** Launching, LCU, playback, DB persistence, UI.

---

#### **R.4 — Replay API + Live Client Data adapters**

**Objective.** Typed, tested clients for `/replay/*` and `/liveclientdata/*` with TLS pinning, timeouts, and retry policy.

**Modules/files.** `riftlens/replay_host/api/{replay_client.py,live_client.py,tls.py,models.py}`; `tests/fakes/fake_replay_server.py`

**Boundaries.** Transport only — no orchestration, no state machine, no launching. Pin Riot's root certificate; `verify=False` is forbidden. Optional endpoints (e.g. `activeplayer`) return `Optional`, never raise. Response models are validated against the R.0 transcript.

**Tests.** T1 against `FakeReplayApiServer` including all misbehaviours in §14. T2 against R.0's recorded transcript.

**Acceptance.** All documented endpoints typed; every T1 failure mode produces the correct `ReplayError`; no unbounded waits; the fake server is reusable by later work orders.

**Do NOT implement.** Launching, sessions, clock calibration, capture, camera.

---

#### **R.5 — Replay launch and session lifecycle**

**Objective.** Implement `ReplayProcessSupervisor` and the §4.2 lifecycle state machine: launch strategy chain, verified readiness, retry/reconnect, teardown.

**Modules/files.** `riftlens/replay_host/{supervisor.py,session.py,launch_strategies.py}`, `riftlens/replay_host/lcu/` (optional, feature-probed)

**Boundaries.** Readiness is defined by §4.2 (200 + `length>0` + verified advancement), not by process start. Live-game safety check before every launch. Session loss never auto-relaunches. LCU is a strategy, never a requirement; `shell_open` and `user_assisted` must both work without it.

**Tests.** T0 for the state machine with a fake clock and fake transport (all transitions, all timeouts). T1 for connect-poll behaviour. T3/T4 for real launch.

**Acceptance.** Cold launch reaches `READY` on real hardware; killing the replay window transitions to `FAILED(SESSION_LOST)` without a relaunch; no orphaned processes after teardown; strategy fallback demonstrably works with the LCU unavailable.

**Do NOT implement.** Clock calibration, click-to-replay, persistence, UI, capture.

---

#### **R.6 — Clock calibration and seeking**

**Objective.** Implement the §5.2 calibration ladder and the §6.1 verified-seek primitive.

**Modules/files.** `riftlens/replay_host/clock/{calibrator.py,anchor_matcher.py}`, `riftlens/replay_host/seek.py`

**Boundaries.** Anchor matching is a **pure function** of (Riot timeline events, live-client events) — no I/O — so it is fully testable on macOS. Reject calibration below the ≥3 anchors / ≤750 ms threshold and degrade to `ESTIMATED`; never silently emit a bad map. Every seek verifies its landing; one retry maximum.

**Tests.** T0 for anchor matching against synthetic sets: clean, noisy, missing events, duplicate champion kills, deliberately wrong offsets. T1 for seek verification including `seeking`-stuck and overshoot. T4 for real calibration.

**Acceptance.** ≥3 anchors with ≤750 ms residual on a real replay; a corrupted anchor set is rejected rather than accepted with a bad offset; seeks land within ±1000 ms.

**Do NOT implement.** Persistence, UI, manual override UI, capture.

---

#### **R.7 — Persistence**

**Objective.** Add the §12.1 tables, repository ports/implementations, and the H.9 backfill migration.

**Modules/files.** `riftlens/persistence/models/gameplay.py`, `riftlens/persistence/repositories/gameplay_repository.py`, `riftlens/domain/ports/gameplay_repository.py`, `alembic/versions/<rev>_gameplay_sources.py`

**Boundaries.** Additive only. H.9 tables retained and readable; the H.9 repository becomes a shim over the new tables. Enforce single-active-`clock_map` in the repository. `capture_interval`/`media_artifact` are created here but unused until R.10.

**Tests.** T0 CRUD; upgrade→downgrade→upgrade; backfill idempotence; a pre-migration DB with H.9 attachments still renders correctly post-migration.

**Acceptance.** An existing H.9 database migrates with zero data loss and the H.9 video path works unchanged afterwards.

**Do NOT implement.** `frame_observation`. UI wiring.

---

#### **R.8 — `RoflGameplaySource` orchestration**

**Objective.** Compose R.2–R.7 into a `GameplaySource` implementation behind `ReplayHostPort`, with `UnsupportedReplayHost` for non-Windows.

**Modules/files.** `riftlens/gameplay/{service.py,factory.py,rofl_source.py}`, `riftlens/replay_host/{port.py,unsupported.py}`

**Boundaries.** `GameplaySourceService.reveal(finding)` is the single public entry point and behaves identically for video and ROFL. `ReplayHostPort` stays coarse (~12 session-oriented methods). Nothing outside `replay_host/windows/` may import Windows APIs — enforce with an import-linter rule in CI.

**Tests.** T0 for the import-boundary lint rule and for `UnsupportedReplayHost` returning typed unavailability on macOS. T1 end-to-end against the fake server. T4 real end-to-end.

**Acceptance.** `reveal()` works against the fake server on macOS and a real replay on Windows with no call-site differences; the full app runs on macOS with a persisted ROFL source present, showing "Available on Windows".

**Do NOT implement.** UI. Capture. Remote hosting.

---

#### **R.9 — Desktop integration**

**Objective.** Ship §13: `Add Gameplay`, the import wizard, the status bar, and click-to-replay.

**Modules/files.** Electron renderer components for the gameplay menu, wizard, and status bar; IPC contracts for source/session state; existing review screen wiring.

**Boundaries.** No coaching logic in the frontend (H.9 rule preserved). Render from capabilities and status, never from `source_type`. No new state machine in the renderer — it subscribes to the backend's. Existing video UI paths untouched.

**Tests.** T0 for IPC contract serialisation; component tests for every status-bar state including all error codes; a regression test that H.9 video attach + manual sync + timestamp seek still works.

**Acceptance.** Full flow on Windows: import → open → click a finding → replay seeks and plays. Full flow on macOS: import is explained-disabled, video path unchanged, a persisted ROFL source renders as unavailable without errors.

**T4 (2026-08-09).** Windows desktop manual demo on `NA1_5617764200` (Kaisa pid 9) **PASSED**. Report: `docs/architecture/r9-desktop-t4-report.md`. A separate H.7/H.8 coaching follow-up found during that demo is recorded in `docs/follow-ups/post-fight-actionable-state.md` and is not an R.9 failure.

**Do NOT implement.** Capture UI. Camera controls. Any change to focus/secondary/strength/metrics/evidence components.

---

#### **R.10 — Frame capture intervals**

**Objective.** Implement `capture_interval(start, end)` over `/replay/recording`, with artifact storage, budgets, and cleanup.

**Modules/files.** `riftlens/replay_host/capture/{capture_service.py,artifact_store.py,retention.py}`, repository wiring for `capture_interval`/`media_artifact`

**Boundaries.** Explicit request only — never implicit, never on the click-to-replay path. Async, cancellable, progress-reporting. Enforce per-review budgets. Every artifact records `game_t_ms` and `clock_map_id`. Cleanup at completion, teardown, startup, and size ceiling.

**Tests.** T0 for retention/GC/budget logic. T1 for recording-progress polling including failure and cancellation. T4 for a real 25-second capture.

**Acceptance.** A real 18:30–18:55 request produces correctly-timestamped artifacts with a valid manifest; cancellation leaves no partials; deleting the review removes the artifacts.

**Do NOT implement.** Any CV. Camera determinism. Video export UI.

---

#### **R.10.5 — Replay coaching overlay (v1)**

**Objective.** External Electron companion overlay for native replay review: Access Overlay launcher, explicit Minimize, HUD-safe navigator + detail, click-to-seek via existing R.8/R.9 reveal. No injection, no live-game coaching, no global League hotkeys.

**T4 (2026-08-11).** Windows desktop manual demo on `NA1_5617764200` **PASSED** for v1. Report: `docs/architecture/r105-overlay-t4-report.md`. Exclusive Direct3D fullscreen cannot composite this overlay; Borderless/Windowed is the accepted v1 path. Further overlay polish is post-v1.

**Do NOT implement.** R.11. H.10. CV. Automatic League display-mode switching. Global shortcuts.

---

#### **R.11 — `FrameObservation` contract (schema only)**

**Objective.** Land the §8.1 type, the `Provenance.VISUAL` enum value, the evidence-labelling path, and the `requires_visual` rule flag — with **zero detectors**.

**Modules/files.** `riftlens/domain/observation/frame_observation.py`, provenance enum extension, H.6 required-input extension, H.8 evidence labelling.

**Boundaries.** No detector, no image processing, no dependency on a CV library. GST is not modified. A rule with `requires_visual: true` is suppressed exactly like any other missing-input rule.

**Tests.** T0: a synthetic `FrameObservation` flows to a labelled evidence item; a `requires_visual` rule suppresses correctly when absent; **a regression test asserting GST output is byte-identical with and without observations present.**

**Acceptance.** Every H.7 rule still produces identical findings; visual evidence is visually distinguishable in the UI; no CV dependency in `requirements.txt`.

**Do NOT implement.** Detectors. Model inference. Any V.x rule.

---

#### **R.12 — Remote Replay Host (DEFERRED — do not build)**

Documented only so R.8's port stays honest. Gated on real user demand.

---

## 16. Proof of concept

### 16.1 Purpose

R.0 exists to answer one question with evidence rather than confidence:

> **Can RiftLens open a real `.rofl` through League and seek it to an arbitrary game timestamp?**

If the answer is no, this entire amendment is wrong and must be revised — and finding that out costs one spike instead of eight work orders and a UI redesign.

### 16.2 Anti-mock mandate

The probe must **fail loudly**. Therefore:

- No mocks, stubs, fakes, or fixtures anywhere in the spike.
- No `try/except` that swallows and continues. Every failure aborts with a non-zero exit and a specific reason.
- No `verify=False` — pin Riot's published root certificate. If TLS pinning fails, that is a finding, not an inconvenience to bypass.
- No fallback to synthetic data if the API is unreachable.
- No "assume it worked" — every command is followed by a read-back that verifies the observable state changed.
- If the replay does not launch, the probe prints exactly why and exits non-zero. **A green run must be impossible to obtain without a real replay actually playing.**

### 16.3 Sequence

Full CLI specification, steps, and the report schema are in **Appendix D**.

---

## 17. Backward compatibility

Guarantees, each with the mechanism that enforces it:

| Guarantee | Mechanism |
|---|---|
| MP4/video attachment keeps working | `VideoGameplaySource` is H.9's code re-expressed in the new interfaces; R.9 carries an explicit regression test |
| Manual SyncMap keeps working | Becomes `LinearOffsetClockMap` with identical math; R.7 backfills existing SyncMaps; behaviour unchanged |
| GST remains analysis source of truth | Nothing in R.0–R.11 writes to GST; R.11 carries a byte-identical-output regression test |
| H.5 metrics unchanged | Not imported, not modified, not touched |
| H.6 findings/evidence unchanged | Only additive: a new provenance enum value and an optional `requires_visual` flag, both defaulting to existing behaviour |
| H.7 rules unchanged | Rule pack files are not edited in the R-series |
| H.8 review assembly unchanged | Reviews are assembled identically; gameplay sources attach to a review, they don't shape it |
| H.9 review UI functional | Only the gameplay-source surface changes; all other components untouched, with a regression test |
| Reviews work with no gameplay source | This was always true and stays true — replay is navigation, not analysis |
| macOS development continues | `UnsupportedReplayHost` + capability-driven UI + a CI import-linter rule preventing Windows imports outside `replay_host/windows/` |

**The one-line invariant:** *RiftLens's analysis has never depended on video, and this amendment does not make it depend on replays.*

---
---

# APPENDICES

## A. Feasibility verdict

**FEASIBLE — with one gate.**

The core requirement (open a real `.rofl`, control it through League, seek to a coaching timestamp, no user-recorded MP4) rests on documented, Riot-supported functionality: the Replay API's `GET/POST /replay/playback` provides read/write access to replay time, pause state, and speed, enabled via `EnableReplayApi=1` in `game.cfg`. This is exactly the primitive the product requires, and Riot ships League Director as a reference implementation of it.

Frame capture for future CV is likewise documented (`POST /replay/recording` to a file path, polled for progress) — meaning RiftLens will never need to render or store a full-match video.

Automatic clock synchronisation is feasible via event anchoring between MATCH-V5 timeline events and the Live Client Data API's `eventdata`, which exposes events with `EventTime`.

**The gate:** three things are *undocumented or unverified* and must be settled by R.0 before further investment:
1. **Programmatic launch.** The LCU replay endpoints are explicitly unsupported by Riot. Mitigation: a launch strategy chain terminating in a user-assisted path that always works.
2. **Live Client Data availability inside a replay.** Assumed, not documented for the replay case. Mitigation: calibration ladder degrades to manual sync.
3. **The `playback.time` ↔ MATCH-V5 `t_ms` relationship.** Assumed near-identity. Mitigation: measure it rather than assume it.

**None of the three can break the core feature** — worst case, the user opens the replay themselves and nudges the sync once. That asymmetry is why the architecture is worth building.

**Not feasible / excluded:** `.rofl` payload decoding, spectator-server emulation, memory reading, injection, and any dependence on historical community tooling.

## B. Recommended GameplaySource architecture

```
                    ┌─────────────────────────────────┐
                    │  Review UI (Electron)           │
                    │  renders from CAPABILITIES      │
                    └──────────────┬──────────────────┘
                                   │ reveal(finding)
                    ┌──────────────▼──────────────────┐
                    │  GameplaySourceService          │  ← the ONLY public surface
                    │  clamp · lead-in · clock convert│
                    └──────────────┬──────────────────┘
                ┌──────────────────┼──────────────────┐
                │                  │                  │
        ┌───────▼──────┐   ┌───────▼──────┐   ┌───────▼────────┐
        │ Descriptor   │   │  ClockMap    │   │ PlaybackCtrl   │
        │ (persisted)  │   │ (immutable)  │   │ (source time)  │
        └──────────────┘   └───────┬──────┘   └───────┬────────┘
                                   │                  │
                     ┌─────────────┴───┐    ┌─────────┴──────────┐
                     │ LinearOffset    │    │ VideoPlayback      │ (cross-platform)
                     │ CalibratedReplay│    │ RoflPlayback       │──┐
                     │ Identity        │    └────────────────────┘  │
                     └─────────────────┘                            │
                                                    ┌───────────────▼────────────┐
                                                    │      ReplayHostPort        │ ← the seam
                                                    └───────────────┬────────────┘
                                              ┌─────────────────────┴──────────┐
                                    ┌─────────▼─────────┐          ┌───────────▼──────────┐
                                    │ WindowsReplayHost │          │ UnsupportedReplayHost│
                                    │ (in-process)      │          │ (macOS/Linux)        │
                                    └───────────────────┘          └──────────────────────┘
```

Key decisions: capability-driven rather than type-driven; `PlaybackController` speaks source time only; `ClockMap` is immutable and confidence-bearing; `ReplayHostPort` is coarse and session-oriented so it can move out-of-process later.

## C. Windows MVP architecture

**Recommendation: run RiftLens Desktop on Windows for replay work, behind an out-of-process-ready port.** (§9, option C.)

- No transport, no serialisation, no file transfer, no distributed failure modes during the phase where we are still establishing whether the Replay API works.
- Matches production reality: the player, the League install, and the `.rofl` are always the same machine.
- macOS development continues unimpeded — roughly 80% of the R-series (R.1, R.2, R.6's anchor matcher, R.7, R.9, R.11, and all T0–T2 tests) is platform-neutral.
- The Windows PC is needed for R.0 and for T3/T4 verification, driven by the R.0 probe CLI running locally there.
- The R.0 CLI doubles as the future remote worker's entrypoint, so nothing is wasted if R.12 is ever built.

**Enforced by CI:** an import-linter rule forbidding any Windows-specific import outside `riftlens/replay_host/windows/`.

## D. Proof-of-concept specification (R.0)

**Deliverable:** `spikes/replay_probe/probe.py` — standalone CLI, no RiftLens imports, expected to be deleted after R.4.

**Invocation**
```
python spikes/replay_probe/probe.py \
    --rofl "C:\Users\me\Documents\League of Legends\Replays\NA1-4567890123.rofl" \
    --league-dir "C:\Riot Games\League of Legends" \
    --match-timeline ./NA1_4567890123_timeline.json \
    --seek 900000 --seek 1500000 --seek 2100000 \
    --report ./probe_report.json \
    --transcript ./session.jsonl
```

**Steps — each prints PASS/FAIL and aborts non-zero on failure**

| # | Step | Verification |
|---|---|---|
| 1 | Validate `.rofl` path and magic bytes | File is real, readable, correct prefix |
| 2 | Extract identity | platformId + gameId from filename; patch from header if readable |
| 3 | Verify install dir | `Config/` and game executable present |
| 4 | Check `game.cfg` | Report `EnableReplayApi` state; **prompt before writing**; back up first |
| 5 | Probe `openapi.json` | `/replay/playback` present in the spec ⇒ API enabled |
| 6 | Confirm no live game | Abort if one is detected |
| 7 | Launch — strategy chain | Record which strategy was attempted and which won |
| 8 | Poll for readiness (≤120 s) | 200 from `/replay/playback` **and** `length > 0` |
| 9 | Verify length | `\|length×1000 − timeline gameDuration\| ≤ 5000 ms` |
| 10 | Advancement test | Unpause; ≥0.9 s replay-time per wall-second over 10 s |
| 11 | Pause test | `time` static across 3 s |
| 12 | Seek tests (×3) | Each lands within ±1000 ms in ≤5 s, `seeking` returns false |
| 13 | Endpoint capability probe | Record availability of every `/replay/*` and `/liveclientdata/*` endpoint |
| 14 | Clock calibration | ≥3 matched anchors, residual ≤750 ms, report the offset |
| 15 | Speed test | Set 2.0, verify advancement rate; restore 1.0 |
| 16 | Teardown | Close session, no orphans, restore `game.cfg` if modified |

**Report schema (abridged)**
```json
{
  "verdict": "PASS",
  "timestamp": "...",
  "league_patch": "15.14",
  "replay_patch": "15.14",
  "launch_strategy_attempted": ["lcu_watch", "shell_open"],
  "launch_strategy_used": "shell_open",
  "time_to_ready_s": 47.2,
  "playback_length_s": 2134.5,
  "timeline_duration_s": 2136.0,
  "length_delta_ms": 1500,
  "advancement_ratio": 0.98,
  "seeks": [
    {"target_game_ms": 900000, "landed_source_ms": 899600,
     "error_ms": -400, "elapsed_s": 1.8, "pass": true}
  ],
  "clock": {"offset_ms": 340, "anchors_matched": 6,
            "residual_ms": 210, "method": "event_anchor_v1"},
  "endpoints": {
    "/replay/playback": "ok", "/replay/recording": "ok",
    "/liveclientdata/eventdata": "ok",
    "/liveclientdata/activeplayer": "404"
  },
  "failures": []
}
```

**Stop/Go.** `verdict != "PASS"` ⇒ R.1 does not begin; the amendment is revised with the probe's findings.
**Artifacts.** Commit `probe_report.json` and `session.jsonl` to `fixtures/replay_api/<patch>/` — the transcript becomes the T2 fixture.

## E. Database / schema changes

Additive only. Full definitions in §12.

**New:** `gameplay_source`, `rofl_source_detail`, `clock_map`, `replay_session` (R.7); `capture_interval`, `media_artifact` (created R.7, used R.10); `frame_observation` (deferred to V.x).

**Migrated:** existing video attachments → `gameplay_source(source_type='video')`; existing SyncMaps → `clock_map(kind='linear_offset', confidence='manual')`.

**Retained:** all H.9 tables, readable, behind a repository shim, for at least one release. Dropped only in a later, separate revision.

**Invariants:** exactly one active `clock_map` per source; `clock_map` is append-only; every timestamp column names its domain (`game_t_ms` vs `source_ms`); backfill is idempotent; downgrade is tested.

## F. UI changes

- `Attach VOD` → **`Add Gameplay ▾`** with `Import League Replay` and `Attach Video`. On macOS the replay item is visible-but-disabled with an explanation.
- A linear import wizard ending at **Ready to open** — launching is always a separate, explicit action.
- A persistent **gameplay status bar** in the review header covering all nine states in §13.3, rendered from capabilities and status rather than source type.
- **Click-to-replay** per §6.1, preserving H.9's per-rule lead-in, with a pending-reveal queue for the not-yet-launched case and a confidence badge when sync is below `CALIBRATED`.
- Video behaviour, manual sync, and every other review component: **unchanged**.

## G. Test strategy

| Tier | Runs | Requires League | Proves |
|---|---|---|---|
| T0 pure unit | Every commit, all platforms | No | Clock math, anchor matching, state machine, sniffer safety, repositories, migrations |
| T1 adapter contract | Every commit, all platforms | No | Real HTTP/TLS/timeout/retry against a real fake server, incl. misbehaviours |
| T2 recorded transcript | Every commit | No | Schema drift against captured real traffic |
| T3 Windows integration | Gated, Windows | Installed, not launched | Install discovery, `game.cfg`, LCU handshake |
| T4 real replay smoke | Manual, gated | Yes, playing | That the product actually works |

Passing T4 is defined by the ten machine-checkable assertions in §14.1, and the report is committed as evidence. CI never depends on League being present.

## H. Revised roadmap

```
COMPLETE:  H.1 … H.9
PARALLEL:  H.10+ continues unblocked

R.0   Replay control PoC (Windows spike)              ← STOP/GO GATE
R.1   GameplaySource domain (pure)                       macOS ok
R.2   .rofl identification and validation (pure)         macOS ok
R.3   Windows environment discovery                      Windows
R.4   Replay API + Live Client Data adapters             macOS ok (fake server); Windows for T3
R.5   Launch and session lifecycle                       Windows
R.6   Clock calibration and seeking                      macOS ok (matcher); Windows for T4
R.7   Persistence + H.9 backfill migration               macOS ok
R.8   RoflGameplaySource orchestration                   macOS ok + Windows T4
R.9   Desktop integration (Add Gameplay, click-to-replay) macOS ok + Windows T4
R.10  Frame capture intervals                            Windows
R.10.5 Replay coaching overlay (v1)                      Windows T4 passed 2026-08-11
R.11  FrameObservation contract (schema only)            macOS ok
R.12  Remote Replay Host                                 DEFERRED

LATER: V.x — computer vision detectors and visual rules
```

R.1 and R.2 may begin on macOS in parallel with R.0, since they are pure and are not invalidated by a negative R.0 result. **R.3 onward is blocked on R.0 passing.**

## I. First Cursor prompt

> **Work order R.0 — Replay Control Proof of Concept (throwaway spike)**
>
> Build a standalone Windows CLI that proves RiftLens can launch a real League `.rofl` replay, connect to Riot's Replay API, read the replay clock, pause/play, and seek to requested game timestamps. This is a disposable spike, not production code.
>
> **Location:** `spikes/replay_probe/` — outside the RiftLens package tree. Do not import anything from `riftlens/`. Do not add anything to the RiftLens package, the database, or the UI. This code is expected to be deleted after R.4.
>
> **CLI**
> ```
> python spikes/replay_probe/probe.py \
>     --rofl <path to .rofl> \
>     --league-dir <path to League install> \
>     --match-timeline <path to MATCH-V5 timeline JSON> \
>     --seek <game_ms> [--seek <game_ms> ...] \
>     --report ./probe_report.json \
>     --transcript ./session.jsonl
> ```
>
> **Implement these steps in order. Each prints `PASS`/`FAIL` with a specific reason, and any failure aborts immediately with a non-zero exit code.**
>
> 1. Validate the `.rofl` path: real file, readable, bounded size, correct magic prefix. Read at most the first 64 KB. Bounds-check every offset before seeking. A metadata parse failure is a warning, not an abort.
> 2. Extract identity: `platformId` and `gameId` from the filename (`REGION-gameid.rofl`); patch and game length from the header JSON if readable.
> 3. Verify the League install directory contains `Config/` and the game executable.
> 4. Read `<league-dir>/Config/game.cfg` and report whether `[General] EnableReplayApi=1` is present. If absent, print the exact change, **prompt for confirmation**, back up to `game.cfg.riftlens.bak`, write minimally preserving all other keys and sections, and tell the user League must be restarted.
> 5. Probe `https://127.0.0.1:2999/swagger/v3/openapi.json` and confirm `/replay/playback` is present in the spec. **Validate TLS against Riot's published root certificate (`https://static.developer.riotgames.com/docs/lol/riotgames.pem`), vendored into the spike. `verify=False` is forbidden.**
> 6. Confirm no live game is in progress; abort if one is.
> 7. Launch the replay using a strategy chain, recording every attempt and the winner: (a) LCU `/lol-replays/...` watch if the client is running and the lockfile is readable; (b) OS shell-open of the `.rofl`; (c) print instructions and wait for the user to open it manually.
> 8. Poll `GET /replay/playback` for up to 120 s. Ready means HTTP 200 **and** `length > 0`.
> 9. Assert `|length × 1000 − timeline gameDuration_ms| ≤ 5000`.
> 10. Unpause and assert replay time advances ≥ 0.9 s per wall-clock second over a 10 s sample.
> 11. Pause and assert `time` is static across 3 s.
> 12. For each `--seek` target: `POST {"paused": true}`, then `POST {"time": target_ms/1000}`, then poll at 4 Hz until `seeking == false`, and assert the landing is within ±1000 ms within 5 s.
> 13. Probe and record the availability of every `/replay/*` and `/liveclientdata/*` endpoint, including which ones 404.
> 14. Calibrate the clock: seek to ~25%, ~50%, ~75%; at each, read `/liveclientdata/eventdata`; match champion-kill events to the MATCH-V5 timeline **by ordinal sequence and killer/victim champion, not by time**; compute `offset_i = riot_t_ms − EventTime_i × 1000`; require ≥ 3 matches with standard deviation ≤ 750 ms; report the median offset and the maximum residual.
> 15. Set speed to 2.0, verify the advancement rate changes, restore 1.0.
> 16. Tear down cleanly: close the session, leave no orphaned processes, restore `game.cfg` if it was modified.
>
> **Output:** `probe_report.json` matching Appendix D's schema, plus `session.jsonl` containing every HTTP request and response (method, URL, status, body, timestamp) — this transcript becomes a permanent test fixture.
>
> **Absolute constraints — this spike must be incapable of passing without a real replay actually playing:**
> - **No mocks, stubs, fakes, or synthetic fallbacks anywhere.**
> - **No exception swallowing.** Every failure aborts with a specific, actionable reason.
> - **No `verify=False`.** Pin the Riot root certificate.
> - **Never assume a POST worked** — always read back and verify the observable state changed.
> - Never elevate privileges. Never write outside the spike directory or the backed-up `game.cfg`.
> - Never send input to the game process.
>
> **Do NOT implement:** any abstraction layer, any RiftLens integration, persistence, UI, frame capture, camera control, computer vision, macOS support, or reusable interfaces. Resist the urge to make this good code. Its only job is to tell us the truth about whether this approach works.
>
> When finished, report the verdict and paste `probe_report.json`.

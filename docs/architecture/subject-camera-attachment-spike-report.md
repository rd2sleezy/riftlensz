# Subject Camera Attachment Spike

**Status:** complete (research spike; not production)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Spike path:** `spikes/subject_camera_attachment/`  
**Match / subject / death:** `NA1_5620410094` · Vladimir pid 6 · `t_ms=839881`  
**Capture window:** `829881–846881`

## 1. Hypothesis

Replay API `selectionName` + `cameraAttached` can deterministically lock the camera to the analyzed participant strongly enough to justify a future `CameraControl.CONTROLLED_SUBJECT` production path.

Champion name is **not** automatically participant identity. The required chain is:

Riot pid → MATCH-V5 metadata → Replay selection token → GET read-back → attached camera → observed subject.

## 2. Actual render fields observed

`GET /replay/render` (live Mac client) and OpenAPI `GET /swagger/v2/swagger.json` `#/definitions/Render` agree.

Identity-relevant fields:

| Field | Type | Role |
|---|---|---|
| `selectionName` | string | Selected replay object name. POST target. Often **clears to `""` during playback** even while attached. |
| `cameraAttached` | bool | Follow/lock toggle. Can stay `true` after `selectionName` clears. |
| `cameraMode` | string | `top` / `path` / `fps`. HUD still says “Directed Camera” under `top`. |
| `cameraPosition` | `{x,y,z}` | y = height; ground is x/z. |
| `selectionOffset` | `{x,y,z}` | Present; stayed `{0,0,0}` in this run. |
| `champions` / `characters` | **bool** | Visibility toggles, not entity lists. |

**No participant id, net id, entity id, or champion id exists on `/replay/render`.**  
`interfaceTarget` is a HUD bool, not a target identity.

Evidence: `spikes/subject_camera_attachment/artifacts/subject_attach_spike.json`.

## 3. Accepted selection identifiers

Using only identities from this match/replay:

| Requested form | Accepted? | Typical GET `selectionName` |
|---|---|---|
| MATCH-V5 `championName` (`Vladimir`, `Ezreal`, `DrMundo`) | **yes** | Riot display name (`immynator`, `Slaydslayer7`, `ronamid`) |
| Case variant (`vladimir`) | **yes** (isolated probe) | `immynator` |
| LCD/display punctuation (`Dr. Mundo`) | **no** | sticky previous |
| Riot display `immynator` | **yes** | `immynator` |
| Tagged `immynator#loler` | **no** (isolated probe from empty) | unchanged |
| Participant id `"6"` | **no** | sticky previous |
| Invalid `NotAChampion` | **no** (silent no-op) | sticky previous / empty |
| Clear `selectionName=""` + `cameraAttached=false` | attach clears; **name is sticky** | name may remain |

LCD `playerlist` uses display forms (`Dr. Mundo`, `Tahm Kench`, `Kog'Maw`, `immynator#loler`). Replay selection wants MATCH-V5 `championName` (`DrMundo`) or untagged `riotIdGameName`. Do not POST LCD strings.

Selection can fail if issued at game start before champions exist. Seek to the window first.

## 4. Participant mapping chain

| Link | Verified? |
|---|---|
| MATCH-V5 pid 6 → `championName=Vladimir`, `riotIdGameName=immynator` | yes (DB / MATCH-V5) |
| This SR roster: all 10 champions unique | yes |
| POST `Vladimir` → GET `immynator` + `cameraAttached=true` | yes (after seek into the window) |
| Reverse-map `immynator` → unique pid 6 | yes |
| Replay API participant/entity id | **no such field** |
| Continuous read-back of who is selected during playback/encode | **no** (`selectionName` often `""` while `cameraAttached=true`) |

Identity is proven only at attach time, by unique reverse-map of the resolved name. It is not a live participant handle.

## 5. Ambiguity behavior

Real match: no duplicate champions. Do not claim real-match duplicate handling.

Synthetic (unit tests): duplicate `Vladimir` with no unique player token → `FAIL_CLOSED`. Duplicate `Vladimir` with unique `riotIdGameName` → champion token rejected; riot-id token allowed.

Live:

- Switching `Fizz` ↔ `Vladimir` resolved to the other player’s riot id when the POST was accepted.
- Invalid / pid / tagged tokens do **not** error; they leave the previous selection.
- Production must treat **unchanged read-back** as “request not accepted,” never as success.

## 6. Attachment semantics

`cameraAttached=true` means the camera is locked to a selected replay object, **not** “locked to pid 6.”

Measured ~4 s of 1× playback after attach + seek to `death-10s`:

- Camera ground position moved.
- Nearest interpolated GST participant was pid 6 on **5/8** samples (`subject_nearest_fraction=0.625`).
- At GST death `(1591, 9726)` camera was **355** units away.
- `selectionName` was already `""` during those samples; `cameraAttached` stayed true.
- ~4 s after death, camera jumped to ~(7494, 6669) — Directed/`top` left the corpse.

So: attach follows the living subject near the death window; it is not a guaranteed corpse lock, and the selected name is not continuously advertised.

## 7. Seek behavior

| Sequence | Result |
|---|---|
| attach → seek | **Attachment does not survive** (`attach_survives_seek=false`) |
| seek → attach | **Works** |
| seek → wait → attach | Works (same as seek then attach here) |

**Rank:** `seek_then_attach` ≫ attach-then-seek.

Capture must re-apply the attach patch after R.10’s internal seek (spike `StickyAttachClient`). Same lesson as path+GST sticky re-apply.

Reconnect/process restart was not tested. A new HTTP client to the same live process still saw the Replay API; that is not a League session reconnect.

## 8. Capture behavior

Attached capture `attach_01M00QHPQ8D016HW6CQT8MEA2Q`:

| | |
|---|---|
| Requested | 17,000 ms |
| Actual | 16,804 ms / 440 frames / covered |
| Wall | 18.04 s |
| Dropouts | 0 |
| After-capture `selectionName` | `""` |
| After-capture `cameraAttached` | `true` |

JPEGs: `spikes/subject_camera_attachment/artifacts/frames/attach/`. Vladimir is in-frame and often centered in the pre-death fight (pool / skirmish with nearby champions). HUD still labels Directed Camera.

## 9. Path+GST comparison

Same window, existing path+GST capture `01M00NSCH421BEY2SP3PADQT8A` vs this attach capture (V.4 unchanged):

| | Path+GST | Attach (`top` + selection) |
|---|---|---|
| Detections (sampled) | **146** | 63 |
| Tracks | 8 | 16 |
| Longest track | **16,717 ms** | 4,509 ms |
| V.4 / V.5 | UNKNOWN | UNKNOWN |
| Subject centering | parked on death coords | follows subject |
| Death-aligned disappearances | 0 | **3, conflicting** |

Path+GST keeps a stable world frame, so tracks persist. Attach/Directed follows the fight, so more champions enter/leave → shorter tracks and conflicting disappearances. Attach is better for “is Vladimir on screen?” Path+GST is better for continuity/identity research on this window.

## 10. V.4 / V.5 downstream effect

No identity-rule changes.

Attach did **not** reach LIKELY. Reasons included `disappearing_tracks=3` / `conflicting evidence`. Path+GST still had `disappearing_tracks=0`.

`CONTROLLED_SUBJECT` is unused in current capture mapping: R.10 `camera_controlled=true` is already `CameraControl.UNKNOWN` (locked, target unproven). This spike does not change that.

## 11. Limitations

- No Replay API participant/entity id.
- `selectionName` often empty while `cameraAttached=true`.
- Seek clears attachment; capture seek must re-apply.
- After death, Directed/`top` may jump away.
- Invalid tokens are silent.
- Tagged riot id and pid strings are not selection keys.
- LCD display names ≠ MATCH-V5 `championName`.
- Duplicate-champion matches were not present; fail-closed is unit-tested only.
- Some champion POSTs fail depending on replay time / whether the unit is selectable.
- Session reconnect untested.

## 12. Final verdict

### `SUBJECT_ATTACH_PARTIAL`

Attachment works visually for this unique-champion match, and attach-time read-back can reverse-map `Vladimir`/`immynator` to pid 6. That is **not** strong enough to justify `CONTROLLED_SUBJECT`.

`cameraAttached=true` is not “camera attached to the analyzed player” unless the attach-time name uniquely reverse-maps **and** that lock is re-established after every seek. Even then the API will not continuously name the target, and Directed camera may leave the subject after death.

Do not change the meaning of `CONTROLLED_SUBJECT` from this spike.

## 13. Recommended next implementation step

Do **not** implement `CONTROLLED_SUBJECT`, V.6 ranking, or capture-policy changes in this work unit.

Smallest future production path, if scheduled later:

1. **Identity mapping** (capture planner, not GST/visual): pid → unique MATCH-V5 `championName` if unique in roster, else unique `riotIdGameName`. Fail closed on duplicate champion when no unique player token exists. Never POST LCD punctuation names or pid strings.
2. **Sequence:** seek to window → POST `{selectionName, cameraAttached: true, cameraMode: "top"}` → GET must reverse-map to the intended pid. If not, **fall back to path+GST**.
3. **Sticky re-apply** after capture seek (same wrapper pattern as path+GST).
4. **Manifest:** requested token, resolved `selectionName`, uniqueness, attach sequence, `cameraAttached` read-back, dropout/restore. Do **not** set `CameraControl.CONTROLLED_SUBJECT` from `camera_controlled=true` alone; add an explicit verified-target field later.
5. Keep path+GST as the default / fallback. It remains the better continuity camera for this death window.

## Files

- `spikes/subject_camera_attachment/` (identity, render parse, attach ranking, live runner, tests)
- `docs/architecture/subject-camera-attachment-spike-report.md` (this file)

Large `.webm` not committed (`~/.riftlens/captures/…`).

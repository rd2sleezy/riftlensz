# macOS `.rofl` Replay API feasibility spike

Throwaway probe. Does **not** modify production RiftLens or `game.cfg`.

## Run

```bash
cd spikes/mac_replay_probe
node probe.mjs
# or
node probe.mjs --rofl "$HOME/Documents/League of Legends/Replays/NA1-5620410094.rofl"
node probe.mjs --skip-launch   # if replay already open
```

Outputs: `session.jsonl`, `probe_report.json`, `SPIKE_REPORT.md`.

Preferred launch on Mac: `--launch-method direct` (uses `GameBaseDir=…/Game`).

## Note

`EnableReplayApi=1` was approved and applied under `[General]` in both:

- `…/LoL/Config/game.cfg`
- `…/LoL/Game/Config/game.cfg` (required for Mac direct launch)

Backups live under `backups/`. Latest verdict: see `SPIKE_REPORT.md`.

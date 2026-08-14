# Replay Camera Control Spike (macOS)

Disposable research spike. Does **not** change production camera/capture policy.

```bash
cd services/analysis
RIFTLENS_CAMERA_SPIKE=1 uv run python ../../spikes/replay_camera_control/run_spike.py
```

Outputs under `spikes/replay_camera_control/artifacts/` (JSON + small JPEGs). Large `.webm` stays in `~/.riftlens/captures/` and is not committed.

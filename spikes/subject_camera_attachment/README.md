# Subject Camera Attachment Spike (macOS)

Disposable research spike. Does **not** change production `CONTROLLED_SUBJECT` semantics.

```bash
cd services/analysis
uv run pytest ../../spikes/subject_camera_attachment/tests -q
RIFTLENS_SUBJECT_ATTACH_SPIKE=1 uv run python ../../spikes/subject_camera_attachment/run_spike.py
```

Outputs under `spikes/subject_camera_attachment/artifacts/` (JSON + small JPEGs).
Large `.webm` stays in `~/.riftlens/captures/` and is not committed.

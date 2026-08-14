# V.6 track-loss diagnostic spike

Offline measurement of why champion-like tracks end ~5.7 s before GST death
`839881` on the framed Mac capture. No production identity/tracker defaults change.

```bash
cd services/analysis
python ../../spikes/v6_track_loss_diagnostic/run_diagnostic.py
```

Optional:

```bash
RIFTLENS_V6_CAPTURE_DIR=~/.riftlens/captures/NA1_5620410094/<id> python ../../spikes/v6_track_loss_diagnostic/run_diagnostic.py
```

Outputs:

- `artifacts/track_loss_diagnostic.json`
- `artifacts/frames/*.jpg` (focus window annotations; do not commit large sets)

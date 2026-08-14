# Glyph atlas (H.9.1)

## Synthetic (`{16,20,24,32}px/`)

**Source: SYNTHETIC.** OpenCV Hershey fonts for deterministic engineering unit
tests. **Not** League HUD crops. Still used when `prefer_league=False` or when
the League atlas is unavailable.

## League (`league/24px/`)

**Source: LEAGUE_CROP.** Classical templates cut from manually labelled real
HUD clock crops of match `NA1_5620410094` (R.10 windowed captures at 1520×982).
`SOURCE.txt` in that directory documents per-glyph origin. Labels are visual /
Replay-API approximate — **never** H.9.1 OCR output as ground truth.

`choose_atlas()` prefers `league/` when complete.

## Corpus

Labelled validation crops live under
`tests/fixtures/vision/clock_corpus/` (see that README). Large `.webm` / `.rofl`
media are **not** committed.

PROJECT: RiftLens — an Electron desktop app that analyzes a League of
Legends match (Riot API data + a gameplay source) and produces timestamped,
evidence-backed coaching feedback.

**Phase 1 gameplay source (2026-08-16):** native `.rofl` is primary (TIER 1).
VIDEO/VOD is optional/experimental (TIER 2). Historical H.9.1/H.10 VIDEO
verdicts remain PARTIAL / BLOCKED_INSUFFICIENT_CORPUS and must not be faked
with ROFL. See `docs/architecture/phase1-rofl-first-acceptance-amendment.md`.

ARCHITECTURE IN ONE PARAGRAPH
An Electron app (TypeScript/React) is the UI shell. All analysis happens in a Python
sidecar (FastAPI, spawned by the Electron main process, bound to 127.0.0.1 on an
ephemeral port with a per-launch bearer token). Every data source writes immutable
`Fact` objects — each carrying a source, a confidence, and a provenance chain — into a
single canonical `GameStateTimeline`. Metrics and rules read ONLY from the
GameStateTimeline. Rules emit `Finding` objects that MUST carry evidence. A
deterministic prioritizer clusters findings into `CoachingItem`s. An LLM narrates those
items from a strictly-schema'd `EvidenceBundle` and its output is mechanically validated
against that bundle; if validation fails, a Jinja template is used instead.

NON-NEGOTIABLE RULES — violating any of these is a bug, not a style preference:
1.  `riftlens/domain/` imports NOTHING from `api/`, `adapters/`, `pipeline/`,
    `analysis/`, or `coaching/`. It is pure Python: dataclasses, enums, math. This is
    enforced by an import-linter contract in CI.
2.  No analysis code reads Riot JSON directly. It reads the GameStateTimeline.
3.  Every `Fact` has `source`, `confidence` (0..1), and `provenance`.
4.  Every `Finding` has at least one `Evidence` item. Constructing a Finding with an
    empty evidence list raises `ValueError`.
5.  No game constant (item cost, ability cooldown, minion gold, respawn timer) is ever
    hardcoded in a rule or metric. It resolves through `PatchDataProvider` using the
    match's own `gameVersion`.
6.  The LLM never sees video, raw Riot JSON, or the database. It sees an EvidenceBundle.
7.  The application is fully functional with the LLM disabled (provider = "null").
8.  Riot API responses for `/matches/{id}` and `/matches/{id}/timeline` are immutable and
    cached forever on disk, content-addressed. A re-analysis makes zero network calls.
9.  The Riot API key never appears in a log, an error message, a stack trace, or the
    renderer process. The structlog processor chain includes a redactor.
10. Time is ALWAYS milliseconds, always an `int`. Game time (`t_ms`) is ms since the
    in-game clock read 00:00. Video time (`t_video_ms`) is ms from the video's first
    presented frame. Never mix them; never use floating-point seconds.

TECH STACK — do not substitute without asking
  Desktop : Electron 3x, TypeScript 5, React 18, Vite via electron-vite, Tailwind,
            Radix UI, Zustand, TanStack Query, zod, pino
  Sidecar : Python 3.12, FastAPI, uvicorn, pydantic v2, SQLAlchemy 2.0 (Core+ORM),
            Alembic, httpx, structlog, tenacity, PyAV, opencv-python-headless, numpy,
            Jinja2, typer (CLI)
  Tooling : pnpm workspaces, uv, ruff, mypy --strict, import-linter, pytest,
            pytest-asyncio, respx, syrupy, vitest, playwright

CODING STANDARDS
- Python: full type annotations, `from __future__ import annotations`, mypy strict
  clean, ruff clean. Prefer frozen dataclasses in `domain/`, pydantic models at API
  boundaries. Use `Protocol` for every adapter so it can be faked in tests.
- TypeScript: strict mode, no `any`, zod schemas for every IPC payload.
- Never write a function longer than ~50 lines without a reason.
- Every public function gets a docstring stating what it returns and what it assumes.
- Tests are written in the same commit as the code, not after.

TESTING PHILOSOPHY
- Golden fixtures live in `services/analysis/tests/fixtures/riot/`. They are real,
  anonymized match + timeline JSON. Most tests run against them.
- Any test that needs the network is wrong. Use `respx` to mock httpx.
- Any test that needs a GPU or a real video longer than 10 seconds is wrong for Phase 1.
- Snapshot tests (syrupy) for structural output; explicit assertions for numbers.

WHEN YOU ARE UNSURE
Ask before inventing a schema, an endpoint, or a Riot API field name. Riot's API has
specific field names and specific gaps (notably: WARD_PLACED and WARD_KILL events have
NO position field, and participantFrames are sampled only once every 60 seconds). Do not
assume data exists.

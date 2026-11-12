# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.5] - 2026-11-13

### Added

- Series memory: an append-only JSONL state file (`data/state.jsonl`, managed by
  the new `scripts/state_store.py`) that gives every generation run bounded
  multi-day context instead of only today's data+news. The latest record per id
  wins; statuses are `routine` (deterministic facts + each report's one-line
  conclusion as `<market>-brief`, 7-day TTL), `open` (pending investigation
  items, 21-day cap, on expiry marked `expired` and noted in the report's
  watchlist, 3-day grace), `resolved` (conclusion written back rather than
  deleted, 7-day TTL), `expired`. `gen_report_cloud.py` prunes dead threads,
  injects the filtered digest (≤30 entries) as a 【系列記憶】prompt block,
  extends the LLM schema with `open_items` / `resolutions` (resolution ids are
  validated against live open items; bad ids are skipped with a warning), and
  appends routine facts + report brief back after the report is written —
  a state failure never fails the already-written report. The `<market>-brief`
  records also fulfil CONTEXT.md §六's cross-market reference in the cloud
  pipeline (TW 13:43 can cite the previous US night's conclusion) without
  reading report files. Ops/future T86-evening-run CLI: `show|add|resolve|prune`;
  `gen_report_cloud.py --dump-prompt PATH` inspects the full prompt without an
  LLM call. Prune rewrites are hygiene only — prompt injection filters by
  `expires`, and git history is the permanent archive.

## [0.2.4] - 2026-11-12

### Changed

- Primary report triggering moved to an external cron-job.org job calling the
  `workflow_dispatch` API (observed working: the 2026-11-12 05:32 Taipei US
  run). GitHub schedules are demoted to one daily backup per workflow, and the
  +30-minute catch-up crons added in 0.2.1 are removed. The idempotent
  trading-day / report-exists gates keep duplicate triggers harmless.

## [0.2.3] - 2026-11-12

### Fixed

- TW close data is now sourced from TWSE official APIs with Yahoo demoted to
  last-resort fallback: the index close comes from the FMTQIK daily report
  (falling back to the MIS snapshot API), stock closes from MIS (falling back
  to Yahoo); chg/pct are re-derived from the official figures and the
  intraday-series / daily-close tails are patched to match. Motivation: the
  published TW 2026-11-11 report carried Yahoo's stale 13:43 snapshot
  (index 44,029.53 / +2,367.83 vs official 44,257.15 / +1,545.23, TSMC 2,380
  vs 2,395) — Yahoo's ^TWII previous-close also skipped the 11/10 session.
  Verified against the 11/11 finals: index/stocks now resolve to the exact
  official values (index=twse_fmtqik, stocks=twse_mis). TW table caption and
  the meta_line prompt updated to attribute TWSE as the data source.
- The existing TW 2026-11-11 report remains as published (historical files
  are never edited); this fix takes effect from the next run.

### Added

- Site archive pagination: only the latest 30 reports render by default
  (overridable via `?page=N` for ops checks) with a 載入更多 button; search
  and market filters always cover the full archive — the cap is display-only,
  and the result count discloses what is shown.

## [0.2.2] - 2026-11-12

### Added

- Site archive (歷史封存): client-side search box with normalized matching
  over title + summary + date + market label — `11/11`, `1111` and
  `2026-11-11` all match the same date, so users can search the way they
  actually remember. Live result count, helpful empty-state hints, and the
  query stacks on the existing market filter chips. Both `input` and
  `search` events are handled so Escape / the native clear button reset
  the query on all browsers.

### Changed

- Archive rows now show a 2-line summary preview, and both title and
  summary are clamped to 2 lines with ellipsis. The limit is display-only —
  manifest.json keeps the full editorial text and the report page keeps the
  full content — so row heights stay consistent as the archive grows.

## [0.2.1] - 2026-11-10

### Fixed

- Snapshot card layout is now deterministic: the `.cards` flex wrapper is
  inserted by Python, not left to the LLM — the cloud-generated TW 2026-11-10
  report had the three snapshot cards stacked full-width because the model
  omitted the wrapper. The published report was repaired in place (layout
  only; no content changed) and all future reports are guaranteed horizontal.
- Quote table: index rows (`^`-prefixed symbols) no longer show a stray `0`
  in the volume column (Yahoo reports 0 volume for indices); they now show —.

### Added

- Catch-up schedules (+30 min) on both report workflows as resilience against
  GitHub Actions scheduler drops; the idempotent trading-day gate makes
  double triggers harmless.

## [0.2.0] - 2026-11-10

### Added

- Fully cloud-hosted automation on GitHub Actions — no local machine required.
  Two scheduled workflows generate and publish reports: TW Mon–Fri 13:43,
  US Tue–Sat 05:33 Taipei time (deliberately off the hour to avoid the
  documented schedule-peak delays).
- Same-day news research without API keys (`fetch_news.py`): Google News RSS
  backbone, Bing News RSS redundancy, publisher feeds (LTN / CNBC /
  MarketWatch), dedupe + 40h window + keyword relevance ranking, plus one
  dynamic query derived from the day's top movers.
- `CONTEXT.md`: distilled series context (market regime, analyst frameworks,
  TW support-level table, writing discipline) consumed by any generator.
- `gen_report_cloud.py`: the LLM writes only the narrative JSON; Python
  deterministically assembles HTML from the shared template and report
  helpers, so quotes/tables/sparklines are always data-exact.
- Workflow safety rails: Taipei-time close guards, idempotent trading-day
  gating (holidays/weekends skip silently), dry-run and force inputs for
  debugging, and automatic `automation-failure` issues on any failure.
- `smoke.yml` one-shot diagnostic: endpoint probe, model discovery, full
  generation into /tmp without publishing.

### Changed

- LLM provider: GitHub Models was retired by GitHub on 2026-07-30; switched
  to the Zhipu bigmodel coding endpoint (`/api/coding/paas/v4`) with
  `glm-5.3-flash` (thinking disabled — reasoning was consuming the entire
  completion budget). SSE streaming with plain-JSON fallback parsing.
- Local ZCode schedules retired; repo documentation consolidated into
  `AUTOMATION.md`.

## [0.1.1] - 2026-11-10

### Fixed

- `report_helpers.quote_table_html`: emit the trailing volume cell only when
  `extra_col` is given — previously a stray empty `<td>` misaligned rows
  against the 6-column header in no-volume mode. Verified all three call
  modes (no extra column / inline note / volume column) produce matching
  header-row column counts.

## [0.1.0] - 2026-11-10

### Added

- GitHub Pages site: latest US/TW closing briefs with iframe embedding and a
  monthly-grouped archive browser driven by `manifest.json`.
- Archive backfill of four existing reports:
  US 2026-11-06, US 2026-11-09, TW 2026-11-09, and the National Stabilization
  Fund special report 2026-11-09.
- Data pipeline scripts: `fetch_us.py` (Yahoo Finance chart API), `fetch_tw.py`
  (Yahoo + TWSE FMTQIK), shared report helpers (cards / quote table / sparkline),
  and `update_manifest.py` to rebuild the site index.
- Shared report HTML template preserving the established zh-Hant visual style.
- Automation runbooks (`AUTOMATION-US.md`, `AUTOMATION-TW.md`) powering the
  scheduled ZCode runs: US Tue–Sat 05:30 Taipei, TW Mon–Fri 13:40 Taipei.
- Idempotent trading-day guard: a run exits quietly when the latest session
  already has a report (covers weekends and market holidays without a calendar).

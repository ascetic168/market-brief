# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

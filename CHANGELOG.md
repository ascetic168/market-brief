# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

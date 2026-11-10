# -*- coding: utf-8 -*-
"""Fetch finalized US close quotes + intraday 5m series + 1-month daily closes.

Data source: Yahoo Finance v8 chart API (unofficial, browser UA required).
Stdlib only — runs on system Python without pip packages.

Usage:
    python fetch_us.py            # fetch latest session, write data/us_<YYYYMMDD>.json
    python fetch_us.py --verbose  # also print per-symbol lines

Output verdict (stdout, single JSON line) — the scheduled run reads this:
    {"ok": true/false, "market": "us", "session_date": "...", "output": "...",
     "report_exists": bool, "reason": "..."}

Trading-day guard: the session date is derived from ^GSPC regularMarketTime in
the exchange timezone (America/New_York via gmtoffset). If a report for that
session already exists under reports/us/<date>/, ok=true but report_exists=true
— the automation exits quietly. Weekends/holidays surface as a stale session
date whose report already exists, so no calendar table is needed.
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

SYMBOLS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI": "Dow Jones",
    "^SOX": "費城半導體",
    "^VIX": "VIX 恐慌指數",
    "^TNX": "美債10年殖利率",
    "NVDA": "Nvidia",
    "AVGO": "Broadcom",
    "PLTR": "Palantir",
    "MU": "Micron",
    "ORCL": "Oracle",
    "CRWV": "CoreWeave",
    "TSLA": "Tesla",
    "TSM": "台積電ADR",
}


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_symbol(sym, verbose):
    """Return (record, session_date_str). Two attempts per symbol."""
    last_err = None
    for attempt in (1, 2):
        try:
            d = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=5m&range=1d" % sym)
            r = d["chart"]["result"][0]
            m = r["meta"]
            price = m.get("regularMarketPrice")
            prev = m.get("chartPreviousClose") or m.get("previousClose")
            chg = price - prev if (price is not None and prev) else None
            pct = chg / prev * 100 if (chg is not None and prev) else None
            # daily closes for ~1 month of context
            md = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=1mo" % sym)
            rd = md["chart"]["result"][0]
            ts = rd.get("timestamp") or []
            closes = rd["indicators"]["quote"][0]["close"]
            daily = [
                {"date": time.strftime("%Y-%m-%d", time.gmtime(t)), "close": round(c, 2)}
                for t, c in zip(ts, closes) if c is not None
            ]
            # session date in the exchange's own timezone (gmtoffset, no tz database needed)
            mt = m.get("regularMarketTime")
            gmtoff = m.get("gmtoffset", -5 * 3600)
            session_date = time.strftime("%Y-%m-%d", time.gmtime(mt + gmtoff)) if mt else None
            rec = dict(
                name=SYMBOLS[sym],
                market_time=mt,
                market_time_et=time.strftime("%Y-%m-%d %H:%M", time.gmtime(mt + gmtoff)) if mt else None,
                close=round(price, 2) if price is not None else None,
                prev=round(prev, 2) if prev else None,
                chg=round(chg, 2) if chg is not None else None,
                pct=round(pct, 2) if pct is not None else None,
                day_low=m.get("regularMarketDayLow"),
                day_high=m.get("regularMarketDayHigh"),
                volume=m.get("regularMarketVolume"),
                series=[round(c, 2) for c in (r["indicators"]["quote"][0]["close"] or []) if c is not None],
                daily=daily,
            )
            if verbose:
                print("%-6s %-16s close=%-10s %+.2f%%  npts=%d  ndaily=%d" % (
                    sym, session_date, rec["close"], rec["pct"] or 0, len(rec["series"]), len(daily)))
            return rec, session_date
        except Exception as e:  # noqa: BLE001 — want a resilient fetcher
            last_err = e
            if attempt == 1:
                time.sleep(2.0)
    return {"name": SYMBOLS[sym], "error": str(last_err)[:200]}, None


def main():
    verbose = "--verbose" in sys.argv
    out = {}
    session_date = None
    for i, sym in enumerate(SYMBOLS):
        rec, sd = fetch_symbol(sym, verbose)
        out[sym] = rec
        if sym == "^GSPC":
            session_date = sd
        if i < len(SYMBOLS) - 1:
            time.sleep(0.8)

    verdict = {"market": "us", "ok": False, "reason": None}
    gspc = out.get("^GSPC", {})
    if "error" in gspc or not session_date:
        verdict["reason"] = "benchmark ^GSPC fetch failed: %s" % gspc.get("error")
        print(json.dumps(verdict, ensure_ascii=False))
        sys.exit(0)
    errors = [s for s, v in out.items() if "error" in v]
    if len(errors) > 3:
        verdict["reason"] = "too many symbol failures: %s" % ",".join(errors)
        print(json.dumps(verdict, ensure_ascii=False))
        sys.exit(0)

    date_compact = session_date.replace("-", "")
    rel = "data/us_%s.json" % date_compact
    dst = os.path.join(ROOT, rel)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"market": "us", "session_date": session_date, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.gmtime(time.time() + 8 * 3600)), "quotes": out}, f, ensure_ascii=False, indent=1)

    report_dir = os.path.join(ROOT, "reports", "us", session_date)
    verdict.update(ok=True, session_date=session_date, output=rel,
                   report_exists=os.path.isfile(os.path.join(report_dir, "index.html")),
                   symbol_errors=errors, reason=None)
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Fetch finalized TW close quotes + intraday 5m series + 1-month daily closes.

Data sources:
  - Yahoo Finance v8 chart API (^TWII + key stocks; official close, 5m series)
  - TWSE FMTQIK daily market report (turnover / index; best-effort, may lag on
    the run day — the report labels it preliminary when today's row is absent)

Stdlib only. Usage and verdict format: see fetch_us.py.

Trading-day guard: ^TWII session date (Asia/Taipei via gmtoffset) must equal
today's Taipei date. On a TW holiday the latest session is an earlier date and
the run exits with ok=false / not_trading_day.
"""
import json
import os
import ssl
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

SYMBOLS = {
    "^TWII": "發行量加權指數",
    "0050.TW": "元大台灣50",
    "2330.TW": "台積電",
    "2454.TW": "聯發科",
    "2317.TW": "鴻海",
    "2308.TW": "台達電",
    "2303.TW": "聯電",
    "3711.TW": "日月光投控",
    "2301.TW": "光寶科",
    "3231.TW": "緯創",
    "3034.TW": "聯詠",
}

# TWSE endpoints need a browser-ish referer; SSL verification off like the
# proven html_build/tw_institutional_verify.py fetcher.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
TWSE_H = dict(UA, Accept="application/json,*/*;q=0.8", Referer="https://www.twse.com.tw/zh/")


def get_json(url, headers=None, timeout=20, context=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
        return json.load(r)


def fetch_symbol(sym, verbose):
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
            md = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=1mo" % sym)
            rd = md["chart"]["result"][0]
            ts = rd.get("timestamp") or []
            closes = rd["indicators"]["quote"][0]["close"]
            daily = [
                {"date": time.strftime("%Y-%m-%d", time.gmtime(t)), "close": round(c, 2)}
                for t, c in zip(ts, closes) if c is not None
            ]
            mt = m.get("regularMarketTime")
            gmtoff = m.get("gmtoffset", 8 * 3600)
            session_date = time.strftime("%Y-%m-%d", time.gmtime(mt + gmtoff)) if mt else None
            rec = dict(
                name=SYMBOLS[sym],
                market_time=mt,
                market_time_tpe=time.strftime("%Y-%m-%d %H:%M", time.gmtime(mt + gmtoff)) if mt else None,
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
                print("%-8s %-16s close=%-10s %+.2f%%  npts=%d  ndaily=%d" % (
                    sym, session_date, rec["close"], rec["pct"] or 0, len(rec["series"]), len(daily)))
            return rec, session_date
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == 1:
                time.sleep(2.0)
    return {"name": SYMBOLS[sym], "error": str(last_err)[:200]}, None


def num(s):
    s = str(s).replace(",", "").strip()
    return float(s) if s not in ("", "--", "None") else None


def fetch_fmtqik(today_compact, verbose):
    """Best-effort TWSE FMTQIK monthly table; keep today's row if published."""
    try:
        month_head = today_compact[:6] + "01"
        j = get_json("https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date=%s" % month_head,
                     headers=TWSE_H, context=CTX)
        if j.get("stat") != "OK":
            return {"error": "stat=%s" % j.get("stat")}
        rows = []
        for row in j.get("data", []):
            p = str(row[0]).split("/")
            if len(p) != 3:
                continue
            dt = "%04d-%02d-%02d" % (int(p[0]) + 1911, int(p[1]), int(p[2]))
            rows.append({"date": dt, "turnover_ntd_1e8": num(row[2]), "index_close": num(row[4]), "change": num(row[5])})
        today_row = next((r for r in rows if r["date"].replace("-", "") == today_compact), None)
        return {"month": rows, "today": today_row}
    except Exception as e:  # noqa: BLE001
        if verbose:
            print("FMTQIK FAIL", e)
        return {"error": str(e)[:150]}


def main():
    verbose = "--verbose" in sys.argv
    now_tpe = time.gmtime(time.time() + 8 * 3600)
    today = time.strftime("%Y-%m-%d", now_tpe)
    today_compact = time.strftime("%Y%m%d", now_tpe)

    verdict = {"market": "tw", "ok": False, "reason": None, "today": today}
    out = {}
    session_date = None
    for i, sym in enumerate(SYMBOLS):
        rec, sd = fetch_symbol(sym, verbose)
        out[sym] = rec
        if sym == "^TWII":
            session_date = sd
        if i < len(SYMBOLS) - 1:
            time.sleep(0.8)

    twii = out.get("^TWII", {})
    if "error" in twii or not session_date:
        verdict["reason"] = "benchmark ^TWII fetch failed: %s" % twii.get("error")
        print(json.dumps(verdict, ensure_ascii=False))
        sys.exit(0)
    if session_date != today:
        verdict["reason"] = "not_trading_day (latest session %s != today %s)" % (session_date, today)
        print(json.dumps(verdict, ensure_ascii=False))
        sys.exit(0)
    errors = [s for s, v in out.items() if "error" in v]
    if len(errors) > 3:
        verdict["reason"] = "too many symbol failures: %s" % ",".join(errors)
        print(json.dumps(verdict, ensure_ascii=False))
        sys.exit(0)

    fmtqik = fetch_fmtqik(today_compact, verbose)

    rel = "data/tw_%s.json" % today_compact
    dst = os.path.join(ROOT, rel)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"market": "tw", "session_date": session_date,
                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", now_tpe),
                   "quotes": out, "fmtqik": fmtqik}, f, ensure_ascii=False, indent=1)

    report_dir = os.path.join(ROOT, "reports", "tw", session_date)
    verdict.update(ok=True, session_date=session_date, output=rel,
                   report_exists=os.path.isfile(os.path.join(report_dir, "index.html")),
                   symbol_errors=errors, fmtqik_today=bool(fmtqik.get("today")), reason=None)
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()

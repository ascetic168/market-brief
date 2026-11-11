# -*- coding: utf-8 -*-
"""Fetch finalized TW close quotes + intraday 5m series + 1-month daily closes.

Data sources — official first, Yahoo as last resort:
  - TWSE FMTQIK daily market report — finalized index close / change / turnover;
    the authoritative ^TWII source when today's row is published (it lags on
    the run day, so the chain falls through to MIS before Yahoo).
  - TWSE MIS snapshot API — per-symbol last/final price (z) and prior close (y);
    after the 13:30:30 closing auction it serves the session finals.
  - Yahoo Finance v8 chart API — 5m series, 1-month daily closes, and whatever
    the two official sources fail to provide. It was historically the sole
    source; its 13:43 snapshot proved stale on 2026-11-11 (index 44,029.53 vs
    official 44,257.15), hence the official-first overlay in apply_official().

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
MIS_H = dict(UA, Accept="application/json,text/plain,*/*;q=0.8",
             Referer="https://mis.twse.com.tw/stock/index.jsp")
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(),
    urllib.request.HTTPSHandler(context=CTX))


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


def _mis_num(d, key):
    s = str(d.get(key, "")).replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _mis_get(raw_sym):
    """One MIS symbol snapshot (raw_sym 't00' = weighted index, else stock code).
    The first request often bootstraps an empty session — retry with cookies."""
    url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_%s.tw" % raw_sym
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=MIS_H)
            with _OPENER.open(req, timeout=15) as r:
                arr = (json.load(r) or {}).get("msgArray") or []
            if arr:
                return arr[0]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.2)
    return None


def fetch_mis_quotes(verbose):
    """MIS snapshot for the index + all stocks; after the closing auction the
    z price is the session final. Returns {sym: {close, prev, high, low}}."""
    out = {}
    for raw in ["t00"] + [s.split(".")[0] for s in SYMBOLS if s != "^TWII"]:
        d = _mis_get(raw)
        if d:
            rec = {"close": _mis_num(d, "z"), "prev": _mis_num(d, "y"),
                   "high": _mis_num(d, "h"), "low": _mis_num(d, "l")}
            if rec["close"] is None and rec["high"] is not None and rec["high"] == rec["low"]:
                rec["close"] = rec["high"]  # one-price session (e.g. limit move)
            if rec["close"] is not None and rec["prev"]:
                out["^TWII" if raw == "t00" else raw + ".TW"] = rec
        time.sleep(0.3)
    if verbose:
        print("MIS OK:", sorted(out.keys()))
    return out


def _override(rec, session_date, close, prev, high=None, low=None, src="official"):
    """Write an official close/prev into a Yahoo record and re-derive chg/pct;
    patch the series/daily tails so charts end at the finalized value. Volume
    intentionally stays Yahoo-side (share units, unlike MIS 張)."""
    rec["close"] = round(close, 2)
    if prev:
        rec["prev"] = round(prev, 2)
    if rec.get("prev"):
        rec["chg"] = round(rec["close"] - rec["prev"], 2)
        rec["pct"] = round((rec["close"] / rec["prev"] - 1) * 100, 2)
    if high is not None:
        rec["day_high"] = high
    if low is not None:
        rec["day_low"] = low
    rec["src"] = src
    if rec.get("series"):
        rec["series"][-1] = rec["close"]
    daily = rec.get("daily") or []
    if daily and daily[-1]["date"] == session_date:
        daily[-1]["close"] = rec["close"]
    elif daily and daily[-1]["date"] < session_date:
        daily.append({"date": session_date, "close": rec["close"]})


def apply_official(out, fmtqik, mis, session_date, verbose):
    """Overlay TWSE official closes onto the Yahoo records — official first,
    Yahoo last. Index: FMTQIK today row → MIS → Yahoo; stocks: MIS → Yahoo.
    Returns {"index": src, "stocks": src_summary} for the verdict."""
    src_idx = "yahoo"
    twii = out.setdefault("^TWII", {})
    today_row = fmtqik.get("today") if isinstance(fmtqik, dict) else None
    if today_row and today_row.get("index_close") is not None:
        chg = today_row.get("change")
        prev = (today_row["index_close"] - chg) if chg is not None else twii.get("prev")
        _override(twii, session_date, close=today_row["index_close"], prev=prev, src="twse_fmtqik")
        src_idx = "twse_fmtqik"
    elif "^TWII" in mis:
        m = mis["^TWII"]
        _override(twii, session_date, close=m["close"], prev=m["prev"],
                  high=m["high"], low=m["low"], src="twse_mis")
        src_idx = "twse_mis"
    srcs = []
    for sym, v in out.items():
        if sym == "^TWII" or "error" in v:
            continue
        if sym in mis:
            m = mis[sym]
            _override(v, session_date, close=m["close"], prev=m["prev"],
                      high=m["high"], low=m["low"], src="twse_mis")
            srcs.append("twse_mis")
        else:
            srcs.append("yahoo")
    src_stock = "yahoo"
    if srcs:
        src_stock = "twse_mis" if all(s == "twse_mis" for s in srcs) else "mixed"
    if verbose:
        print("sources: index=%s stocks=%s" % (src_idx, src_stock))
    return {"index": src_idx, "stocks": src_stock}


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

    mis = fetch_mis_quotes(verbose)
    fmtqik = fetch_fmtqik(today_compact, verbose)
    sources = apply_official(out, fmtqik, mis, session_date, verbose)

    rel = "data/tw_%s.json" % today_compact
    dst = os.path.join(ROOT, rel)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"market": "tw", "session_date": session_date,
                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", now_tpe),
                   "quotes": out, "fmtqik": fmtqik, "sources": sources}, f, ensure_ascii=False, indent=1)

    report_dir = os.path.join(ROOT, "reports", "tw", session_date)
    verdict.update(ok=True, session_date=session_date, output=rel,
                   report_exists=os.path.isfile(os.path.join(report_dir, "index.html")),
                   symbol_errors=errors, fmtqik_today=bool(fmtqik.get("today")),
                   sources=sources, reason=None)
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()

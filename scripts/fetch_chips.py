# -*- coding: utf-8 -*-
"""TW chip supplement (tw-chips): fetch TWSE institutional + margin daily finals
and silently append them into the series memory (data/state.jsonl) as routine
facts — no LLM, no report page. The next 13:43 TW report picks them up via the
【系列記憶】digest, so it finally has a chips section (prior trading day only —
same-day T86 stays forbidden by the honesty clause).

Why 21:50 Taipei: T86 totals publish ~17:00, margin balances ~21:30; one run
catches both.

Endpoints (verified 2026-11-13; note the case/path quirks):
  BFI82U  https://www.twse.com.tw/rwd/zh/fund/BFI82U  (UPPERCASE — lowercase
          bfi82u 404s to page-not-found)
  MI_MARGN https://www.twse.com.tw/exchangeReport/MI_MARGN  (old-style path —
          the rwd/zh/marginTrade path 404s)

Usage:
    python scripts/fetch_chips.py [--date YYYYMMDD]   # default: today, Taipei

Verdict (single-line JSON, same convention as the other fetchers):
    ok=true  appended: [topics], skipped: [same-day topics already in state]
    ok=false reason: fetch/parse/stale failure → workflow opens an alert issue
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from state_store import append_records, latest_map, load_records, make_record  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.environ.get("MARKET_BRIEF_STATE") or os.path.join(ROOT, "data", "state.jsonl")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# Same TWSE quirks as fetch_tw.py: browser-ish referer + cookie jar + unverified SSL.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
H = dict(UA, Accept="application/json,*/*;q=0.8", Referer="https://www.twse.com.tw/zh/")
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(),
    urllib.request.HTTPSHandler(context=CTX))

URL_T86 = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=%s&type=day&response=json"
URL_MGN = "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date=%s&selectType=ALL"


def _tpe_date(ts=None):
    return time.strftime("%Y-%m-%d", time.gmtime((ts or time.time()) + 8 * 3600))


def get_json(url, tries=3):
    """First requests may bootstrap an empty session and land on an HTML page
    (page-not-found or a gate) — retry with the warmed-up cookie jar."""
    last_err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=H)
            with _OPENER.open(req, timeout=30) as r:
                final_url, raw = r.geturl(), r.read()
            if raw.lstrip()[:1] in (b"{", b"["):
                return json.loads(raw.decode("utf-8", "ignore"))
            last_err = RuntimeError("non-json response (final url %s)" % final_url)
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(3)
    raise last_err


def _num(s):
    return int(str(s).replace(",", "").strip())


def _diff(v):
    """買賣差額 in 億元, media phrasing (買超/賣超)."""
    y = v / 1e8
    if abs(y) < 0.05:
        return "買賣持平"
    return "買超 {:,.1f} 億".format(y) if y > 0 else "賣超 {:,.1f} 億".format(-y)


def parse_t86(d, date_req):
    if d.get("stat") != "OK":
        raise RuntimeError("BFI82U stat=%s" % d.get("stat"))
    if d.get("date") != date_req:
        raise RuntimeError("BFI82U stale: api date %s != requested %s" % (d.get("date"), date_req))
    fdi = inv = own = total = None
    for row in d.get("data") or []:
        name, diff = row[0], _num(row[3])
        if name.startswith("外資及陸資") or name == "外資自營商":
            fdi = (fdi or 0) + diff
        elif name.startswith("自營商"):
            own = (own or 0) + diff
        elif name == "投信":
            inv = diff
        elif name == "合計":
            total = diff
    if total is None or inv is None or fdi is None or own is None:
        raise RuntimeError("BFI82U missing expected rows (外資/投信/自營商/合計)")
    return "三大法人合計%s；外資%s、投信%s、自營商%s" % (_diff(total), _diff(fdi), _diff(inv), _diff(own))


def parse_mgn(d, date_req):
    if d.get("stat") != "OK":
        raise RuntimeError("MI_MARGN stat=%s" % d.get("stat"))
    if d.get("date") != date_req:
        raise RuntimeError("MI_MARGN stale: api date %s != requested %s" % (d.get("date"), date_req))
    tbl = next((t for t in d.get("tables") or [] if "信用交易統計" in (t.get("title") or "")), None)
    if tbl is None:
        raise RuntimeError("MI_MARGN: no 信用交易統計 table")
    rows = {r[0]: r for r in tbl.get("data") or []}
    fin, shr = rows.get("融資金額(仟元)"), rows.get("融券(交易單位)")
    if fin is None or shr is None:
        raise RuntimeError("MI_MARGN missing 融資金額/融券 rows")
    # 仟元 → 億元 (÷1e5); balances: [前日餘額, 今日餘額]
    fin_bal, fin_chg = _num(fin[5]) / 1e5, (_num(fin[5]) - _num(fin[4])) / 1e5
    shr_bal, shr_chg = _num(shr[5]), _num(shr[5]) - _num(shr[4])
    return "融資餘額 {:,.1f} 億（{:+,.1f} 億）；融券 {:,} 張（{:+,} 張）".format(
        fin_bal, fin_chg, shr_bal, shr_chg)


def main():
    ap = argparse.ArgumentParser(description="fetch TWSE T86 + margin finals into series memory")
    ap.add_argument("--date", default=None, help="YYYYMMDD; default today Taipei (backfill/debug)")
    a = ap.parse_args()

    today = _tpe_date()
    date_req = a.date or today.replace("-", "")
    if a.date and a.date > today.replace("-", ""):
        print(json.dumps({"ok": False, "error": "future date %s" % a.date}))
        sys.exit(1)

    latest = latest_map(load_records(STATE_PATH))
    # Dedup keys off the session_date field (id prefixes are creation-day based,
    # so a backfilled older date must still block a second ingest of that date).
    have = {r["topic"] for r in latest.values()
            if r["topic"] in ("tw-t86", "tw-margin") and r.get("session_date") == date_req}
    want = [t for t in ("tw-t86", "tw-margin") if t not in have]

    texts = {}
    try:
        if "tw-t86" in want:
            texts["tw-t86"] = parse_t86(get_json(URL_T86 % date_req), date_req)
        if "tw-margin" in want:
            texts["tw-margin"] = parse_mgn(get_json(URL_MGN % date_req), date_req)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "session_date": date_req,
                          "error": "%s: %s" % (type(e).__name__, str(e)[:200])}))
        sys.exit(1)

    existing_ids = tuple(latest.keys())
    recs = []
    for topic, text in texts.items():
        rec = make_record("routine", topic, text, today=_tpe_date(),
                          existing_ids=existing_ids + tuple(r["id"] for r in recs))
        rec["session_date"] = date_req  # ingest dedup key (survives backfills)
        recs.append(rec)
    n = append_records(STATE_PATH, recs)
    verdict = {"ok": True, "session_date": date_req, "appended": [r["topic"] for r in recs],
               "skipped": sorted(have), "duplicate": n == 0}
    verdict.update(texts)
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()

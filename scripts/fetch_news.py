# -*- coding: utf-8 -*-
"""Fetch same-day market news for report generation.

Layered sources, all key-free:
  1. Google News RSS keyword search (backbone, zh-TW / en-US locales)
  2. Bing News RSS keyword search (different host — true redundancy)
  3. Publisher RSS breadth (TW: LTN business; US: CNBC, MarketWatch)

Plus one dynamic query from the freshest data/<market>_*.json (top mover).

Stdlib only. Usage:
    python fetch_news.py tw|us [--verbose]

Writes data/news_<market>_<YYYYMMDD>.json and prints a single-line JSON
verdict: {"ok": bool, "market": ..., "n_items": N, "output": ..., "errors": [...]}
Zero items is not fatal — the report proceeds data-only and says so.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}
WINDOW_H = 40          # keep news published within this many hours
MAX_ITEMS = 22
GOOGLE_BUDGET_MS = 12_000   # per-request timeout guard

LOCALE = {
    "tw": "hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "us": "hl=en-US&gl=US&ceid=US:en",
}
BING_MKT = {"tw": "zh-TW", "us": "en-US"}
BASE_QUERIES = {
    "tw": ["台股 收盤", "加權指數 收盤", "外資 買賣超 台股", "台股 盤後 解析"],
    "us": ["S&P 500 close", "Nasdaq stock market close", "stock market today recap", "stock market close why"],
}
BING_QUERIES = {
    "tw": ["台股 收盤", "加權指數 外資"],
    "us": ["S&P 500 close", "Nasdaq close"],
}
PUB_FEEDS = {
    "tw": [("https://news.ltn.com.tw/rss/business.xml", "自由財經")],
    "us": [("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC"),
           ("https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch")],
}
KEYWORDS = {
    "tw": ["台股", "加權", "外資", "台積電", "聯發科", "鴻海", "國安基金", "櫃買", "法人", "融資", "期貨", "半導體"],
    "us": ["S&P", "Nasdaq", "Dow", "stock", "market", "Fed", "Nvidia", "NVDA", "chip", "semiconductor", "yield", "VIX", "AI"],
}
INDEX_PREFIX = "^"


def fetch_rss(url, fixed_source=None, timeout=15):
    """Return list of {title, link, source, pub_dt(datetime|None)}; raise on failure."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        source = fixed_source or (it.findtext("source") or "").strip() or ""
        pub = None
        pd = it.findtext("pubDate")
        if pd:
            try:
                pub = parsedate_to_datetime(pd).astimezone()
            except Exception:  # noqa: BLE001 — tolerate odd date formats
                pub = None
        out.append({"title": re.sub(r"\s+", " ", title), "link": link, "source": source, "pub_dt": pub})
    return out


def gnews_url(q, market):
    return "https://news.google.com/rss/search?q=%s&%s" % (urllib.parse.quote_plus(q), LOCALE[market])


def bing_url(q, market):
    return "https://www.bing.com/news/search?q=%s&format=RSS&setmkt=%s" % (urllib.parse.quote_plus(q), BING_MKT[market])


def dedupe_key(title):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", title.lower())


def score(item, market):
    t = item["title"].lower()
    return sum(1 for k in KEYWORDS[market] if k.lower() in t)


def dynamic_query(market):
    """Top mover from the freshest data/<market>_*.json → one extra query."""
    try:
        files = sorted(glob.glob(os.path.join(ROOT, "data", "%s_*.json" % market)))
        if not files:
            return None
        with open(files[-1], encoding="utf-8") as f:
            d = json.load(f)
        movers = [(abs(v.get("pct") or 0), sym, v.get("name") or sym)
                  for sym, v in d.get("quotes", {}).items()
                  if not sym.startswith(INDEX_PREFIX) and "error" not in v]
        movers.sort(reverse=True)
        if movers and movers[0][0] >= 3.0:
            name = movers[0][2]
            return "%s %s" % (name, "收盤" if market == "tw" else "stock")
    except Exception:  # noqa: BLE001 — dynamic query is best-effort only
        return None
    return None


def main():
    market = "tw" if "tw" in sys.argv else "us"
    verbose = "--verbose" in sys.argv
    now = time.time()
    queries = list(BASE_QUERIES[market])
    dq = dynamic_query(market)
    if dq:
        queries.append(dq)
        if verbose:
            print("dynamic query:", dq)

    items, errors = [], []
    jobs = [("google", gnews_url(q, market)) for q in queries]
    jobs += [("bing", bing_url(q, market)) for q in BING_QUERIES[market]]
    jobs += [("feed", url) for url, _ in PUB_FEEDS[market]]
    for kind, url in jobs:
        try:
            got = fetch_rss(url, fixed_source=dict(PUB_FEEDS[market]).get(url))
            for it in got:
                it["kind"] = kind
            items.extend(got)
            if verbose:
                print("%-6s %-60s -> %d" % (kind, url[:60], len(got)))
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001 — one source failing must not kill the run
            errors.append("%s: %s" % (kind, str(e)[:80]))

    # dedupe + window filter + relevance rank
    seen, kept = set(), []
    for it in items:
        k = dedupe_key(it["title"])
        if not k or k in seen:
            continue
        seen.add(k)
        pub = it.get("pub_dt")
        if pub is not None and (now - pub.timestamp()) > WINDOW_H * 3600:
            continue
        if pub is None and it["kind"] == "feed":   # undated feed items: skip
            continue
        kept.append(it)
    kept.sort(key=lambda i: (-score(i, market), -(i["pub_dt"].timestamp() if i["pub_dt"] else 0)))
    kept = kept[:MAX_ITEMS]

    date_compact = time.strftime("%Y%m%d", time.gmtime(now + 8 * 3600))
    rel = "data/news_%s_%s.json" % (market, date_compact)
    doc = {
        "market": market,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.gmtime(now + 8 * 3600)),
        "items": [{"title": i["title"], "source": i["source"], "link": i["link"],
                   "published": i["pub_dt"].strftime("%Y-%m-%d %H:%M") if i["pub_dt"] else None}
                  for i in kept],
    }
    with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": len(kept) > 0, "market": market, "n_items": len(kept),
                      "output": rel, "errors": errors[:4]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Rebuild manifest.json from the reports/ tree.

- Entry key is the report file path; titles/summaries already present in
  manifest.json are preserved verbatim (summaries are editorial content).
- New reports discovered on disk get title from <title> and a trimmed
  extraction of the .summary block.
- Existing entries whose files disappeared are dropped.

Usage: python update_manifest.py [summary_chars]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETS = ("us", "tw", "special")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
TAG_RE = re.compile(r"<[^>]+>")


def extract(path, summary_chars):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"<title>([^<]*)</title>", html)
    title = m.group(1).strip() if m else os.path.basename(os.path.dirname(path))
    # drop the trailing (YYYY-MM-DD) the titles carry
    title = re.sub(r"（\d{4}-\d{2}-\d{2}[^）]*）\s*$", "", title).strip()
    m = re.search(r'<div class="summary">(.*?)</div>', html, re.S)
    summary = ""
    if m:
        summary = re.sub(r"\s+", " ", TAG_RE.sub("", m.group(1))).strip()
        summary = summary[:summary_chars].rstrip()
    return title, summary


def main():
    summary_chars = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    mpath = os.path.join(ROOT, "manifest.json")
    old = {}
    if os.path.isfile(mpath):
        with open(mpath, encoding="utf-8") as f:
            old = {e["file"]: e for e in json.load(f).get("reports", [])}

    entries = []
    for mkt in MARKETS:
        base = os.path.join(ROOT, "reports", mkt)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base), reverse=True):
            fpath = os.path.join(base, name, "index.html")
            if not os.path.isfile(fpath):
                continue
            dm = DATE_RE.match(name)
            if not dm:
                continue
            rel = "reports/%s/%s/index.html" % (mkt, name)
            if rel in old and old[rel].get("summary"):
                e = old[rel]
            else:
                title, summary = extract(fpath, summary_chars)
                e = {"market": mkt, "date": dm.group(1), "title": title, "summary": summary}
                if rel in old:
                    e.update({k: v for k, v in old[rel].items() if k not in e})
                elif mkt == "special":
                    e["slug"] = name
            e["market"], e["date"], e["file"] = mkt, dm.group(1), rel
            entries.append(e)

    entries.sort(key=lambda e: (e["date"], ["us", "tw", "special"].index(e["market"])), reverse=True)
    doc = {"generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S+08:00", __import__("time").gmtime(__import__("time").time() + 8 * 3600)), "reports": entries}
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("manifest.json rebuilt: %d reports" % len(entries))


if __name__ == "__main__":
    main()

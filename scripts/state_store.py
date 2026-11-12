# -*- coding: utf-8 -*-
"""Series memory store: append-only JSONL state file (data/state.jsonl).

gives the daily report pipeline a bounded, self-expiring memory that survives
across runs. Design (agreed 2026-11-13):

- Every state change appends a new JSONL line; the LAST record per `id` wins.
  Threads that answer a question share the question's id (open -> resolved).
- Statuses and default TTLs:
    routine  — deterministic daily facts written by Python (closes, turnover,
               the report's one-line conclusion as <market>-brief); 7 days.
    open     — pending investigation item (待查, from the LLM watchlist);
               21-day hard deadline. On expiry the pipeline appends an
               `expired` marker so the report can note the timeout visibly,
               and the thread is pruned after the marker's own TTL (3 days).
    resolved — conclusion written back (never delete-on-resolve: answers are
               worth more than questions); 7 days, then pruned.
    expired  — timeout marker for a dead `open` thread; 3-day grace.
- Prompt injection filters by `expires` (correctness never depends on prune
  having run); pruning rewrites the file for hygiene — git history is the
  permanent archive.

CLI (for tests and the future T86 evening run):
    python scripts/state_store.py show [--all]
    python scripts/state_store.py add routine|open --topic T --text "..." [--ttl N]
    python scripts/state_store.py resolve ID --text "..."
    python scripts/state_store.py prune
    [--file PATH] overrides data/state.jsonl everywhere.
Prints single-line JSON verdicts (like the other scripts); `show` prints the
digest text.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_helpers import fmt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "data", "state.jsonl")

TTL_DAYS = {"routine": 7, "open": 21, "resolved": 7, "expired": 3}
DIGEST_ORDER = {"expired": 0, "open": 1, "resolved": 2, "routine": 3}
DIGEST_TAG = {"expired": "逾時結案", "open": "待查", "resolved": "結論", "routine": "常規"}
MARKET_NAME = {"us": "美股", "tw": "台股"}


def _tpe_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)


def _today_tpe():
    return _tpe_now().strftime("%Y-%m-%d")


def _iso_tpe():
    return _tpe_now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _plus_days(date_str, days):
    d = datetime.date(*(int(x) for x in date_str.split("-")))
    return (d + datetime.timedelta(days=days)).strftime("%Y-%m-%d")


def _make_id(existing_ids, date_compact):
    seq = 0
    for i in existing_ids:
        if i.startswith(date_compact + "-"):
            try:
                seq = max(seq, int(i.rsplit("-", 1)[1]))
            except (IndexError, ValueError):
                pass
    return "%s-%02d" % (date_compact, seq + 1)


def make_record(status, topic, text, ttl_days=None, today=None, existing_ids=()):
    today = today or _today_tpe()
    ttl = TTL_DAYS[status] if ttl_days is None else ttl_days
    rec = {
        "id": _make_id(existing_ids, today.replace("-", "")),
        "created": _iso_tpe(),
        "status": status,
        "expires": _plus_days(today, ttl),
        "topic": topic,
        "text": text,
    }
    if status == "resolved":
        rec["resolved_date"] = today
    return rec


def load_records(path):
    """Read all JSONL records; tolerate a torn tail line rather than dying."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def latest_map(records):
    m = {}
    for r in records:
        m[r["id"]] = r  # later lines win: open -> resolved / expired
    return m


def append_records(path, records):
    if not records:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)


def prune_state(path, today=None, write=True):
    """Expire open threads past their deadline, then drop threads fully past
    their life. Returns (latest_map after pruning+markers, newly_expired list).
    write=False only computes (used by --dump-prompt / show / resolve checks).
    """
    today = today or _today_tpe()
    records = load_records(path)
    latest = latest_map(records)

    markers = []
    newly_expired = []
    for rid, rec in latest.items():
        if rec.get("status") == "open" and rec.get("expires", "") < today:
            marker = make_record("expired", rec.get("topic", "general"),
                                 "追蹤逾時結案（原項：%s）" % rec.get("text", ""), today=today)
            marker["id"] = rid  # same thread; latest-wins supersedes the question
            markers.append(marker)
            newly_expired.append({"id": rid, "topic": rec.get("topic", ""), "text": rec.get("text", "")})

    all_records = records + markers
    latest = latest_map(all_records)
    alive_ids = {rid for rid, r in latest.items() if r.get("expires", "") >= today}
    kept = [r for r in all_records if r["id"] in alive_ids]
    if write and (markers or len(kept) != len(records)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return latest_map(kept), newly_expired


def state_digest(latest, today=None, max_entries=30):
    """Bounded text block for prompt injection. Order: expired (must be noted),
    open, resolved, routine; newest id first within each group."""
    today = today or _today_tpe()
    items = [r for r in latest.values() if r.get("expires", "") >= today]
    items.sort(key=lambda r: r.get("id", ""), reverse=True)
    items.sort(key=lambda r: DIGEST_ORDER.get(r.get("status"), 9))
    if not items:
        return "（目前無系列記憶記錄）"
    lines = []
    for r in items[:max_entries]:
        st, rid = r.get("status"), r.get("id", "?")
        extra = ""
        if st == "open":
            extra = "（期限 %s）" % r.get("expires", "?")
        elif st == "resolved":
            extra = "（%s 結案）" % r.get("resolved_date", "?")
        lines.append("- [%s %s] (%s) %s%s" % (DIGEST_TAG.get(st, st), rid, r.get("topic", "general"),
                                              r.get("text", ""), extra))
    if len(items) > max_entries:
        lines.append("…（其餘 %d 筆略）" % (len(items) - max_entries))
    return "\n".join(lines)


def _q(quotes, sym):
    v = quotes.get(sym) or {}
    return v if v and "error" not in v else None


def make_routine_facts(market, data, today=None, existing_ids=()):
    """Deterministic daily facts from the fetched data JSON — Python writes
    numbers, the LLM never does (same discipline as the HTML assembly)."""
    today = today or _today_tpe()
    quotes = data.get("quotes", {})
    recs = []

    def add(topic, text):
        recs.append(make_record("routine", topic, text, today=today,
                                existing_ids=tuple(existing_ids) + tuple(r["id"] for r in recs)))

    parts = []
    if market == "tw":
        v = _q(quotes, "^TWII")
        if v:
            parts.append("加權 %s（%+.2f%%）" % (fmt(v.get("close")), v.get("pct") or 0))
        fq = (data.get("fmtqik") or {}).get("today") or {}
        if fq.get("turnover_ntd_1e8"):
            parts.append("成交值約 {:,.0f} 億".format(fq["turnover_ntd_1e8"]))
        for sym in ("2330.TW", "2454.TW", "0050.TW"):
            v = _q(quotes, sym)
            if v:
                parts.append("%s %s（%+.2f%%）" % (v.get("name") or sym.split(".")[0], fmt(v.get("close")), v.get("pct") or 0))
    else:
        for sym in ("^GSPC", "^IXIC", "^SOX", "NVDA"):
            v = _q(quotes, sym)
            if v:
                parts.append("%s %s（%+.2f%%）" % (v.get("name") or sym, fmt(v.get("close")), v.get("pct") or 0))
        v = _q(quotes, "^VIX")
        if v:
            parts.append("VIX %s" % fmt(v.get("close")))
        v = _q(quotes, "^TNX")
        if v:
            parts.append("10Y殖利率 %s%%" % fmt(v.get("close")))
    if parts:
        add("market", "；".join(parts))
    return recs


def make_report_brief(market, result, session_date, today=None, existing_ids=()):
    """Capture this report's one-line conclusion as routine memory, so the
    OTHER market's next run can reference it (fulfils CONTEXT.md §六's
    cross-reference without reading report files)."""
    summary = re.sub(r"<[^>]+>", "", result.get("summary_html") or "").strip()
    if not summary:
        return []
    title = (result.get("title") or "").strip()
    text = "%s收盤快報《%s》（%s）：%s" % (MARKET_NAME.get(market, market), title, session_date, summary)
    return [make_record("routine", "%s-brief" % market, text[:400], today=today, existing_ids=existing_ids)]


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="series memory state store (data/state.jsonl)")
    ap.add_argument("cmd", choices=["show", "add", "resolve", "prune"])
    ap.add_argument("arg", nargs="?", help="add: routine|open / resolve: record id")
    ap.add_argument("--topic", default="general")
    ap.add_argument("--text", default="")
    ap.add_argument("--ttl", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="show: dump raw latest records")
    ap.add_argument("--file", default=DEFAULT_PATH)
    a = ap.parse_args()

    def die(msg):
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        sys.exit(1)

    if a.cmd == "show":
        latest, _ = prune_state(a.file, write=False)
        if a.all:
            for r in latest.values():
                print(json.dumps(r, ensure_ascii=False))
        else:
            print(state_digest(latest))
        return

    if a.cmd == "add":
        if a.arg not in ("routine", "open"):
            die("add needs kind routine|open (got %r)" % a.arg)
        if not a.text:
            die("add needs --text")
        rec = make_record(a.arg, a.topic, a.text, ttl_days=a.ttl,
                          existing_ids=tuple(latest_map(load_records(a.file)).keys()))
        n = append_records(a.file, [rec])
        print(json.dumps({"ok": True, "added": n, "record": rec}, ensure_ascii=False))
        return

    if a.cmd == "resolve":
        if not a.arg or not a.text:
            die("resolve needs a record id and --text")
        latest = latest_map(load_records(a.file))
        tgt = latest.get(a.arg)
        if not tgt or tgt.get("status") != "open":
            die("id %s is not an open item" % a.arg)
        rec = make_record("resolved", tgt.get("topic", "general"), a.text)
        rec["id"] = a.arg
        n = append_records(a.file, [rec])
        print(json.dumps({"ok": True, "added": n, "record": rec}, ensure_ascii=False))
        return

    if a.cmd == "prune":
        latest, expired = prune_state(a.file, write=True)
        print(json.dumps({"ok": True, "alive": len(latest), "expired_marked": len(expired)}, ensure_ascii=False))


if __name__ == "__main__":
    _cli()

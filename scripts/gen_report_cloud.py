# -*- coding: utf-8 -*-
"""Cloud report generator: GitHub Models writes the narrative, Python assembles.

Pipeline: data json + news json + CONTEXT.md + series memory (data/state.jsonl,
          via state_store.py) + report_helpers blocks
          → one LLM call returning strict JSON (title / meta / summary /
          sections / open_items / resolutions)
          → deterministic HTML assembly from templates/report_base.html,
          then routine facts + report brief + LLM open/resolved records are
          appended back to the state file.

Usage:
    python scripts/gen_report_cloud.py <market us|tw> <data.json> <news.json> \
        [--out-dir DIR] [--model MODEL] [--max-news 18] [--dump-prompt PATH]

--dump-prompt PATH assembles system+user prompts (with the state digest; prune
runs read-only) and exits before the LLM call — debugging aid for smoke runs.

Env: LLM_API_TOKEN (API key for the OpenAI-compatible endpoint), optional
LLM_BASE_URL / LLM_MODEL (defaults: Zhipu bigmodel.cn coding endpoint, glm-5.3-flash). Default output
goes to reports/<market>/<session_date>/index.html; --out-dir overrides for
testing. Prints a single-line JSON verdict.
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_helpers import cards_html, fmt, quote_table_html, sparkline_html  # noqa: E402
from state_store import (append_records, make_record, make_report_brief,  # noqa: E402
                         make_routine_facts, prune_state, state_digest)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# OpenAI-compatible endpoint; default is Zhipu bigmodel.cn coding plan (GLM). Override via env.
ENDPOINT = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "glm-5.3-flash")
# Series memory file; MARKET_BRIEF_STATE overrides for tests.
STATE_PATH = os.environ.get("MARKET_BRIEF_STATE") or os.path.join(ROOT, "data", "state.jsonl")

CARDS_SPECS = {
    "us": [("^GSPC", "S&P 500", "GSPC"), ("^IXIC", "Nasdaq Composite", "IXIC"), ("^SOX", "費城半導體", "SOX")],
    "tw": [("^TWII", "發行量加權指數", "TWII"), ("2330.TW", "台積電", "2330"), ("0050.TW", "元大台灣50", "0050")],
}
SPARK_SPECS = {
    "us": [("^GSPC", "S&P 500", "GSPC", "09:30–16:00 美東"), ("^IXIC", "Nasdaq Composite", "IXIC", "09:30–16:00 美東"), ("NVDA", "Nvidia", "NVDA", "09:30–16:00 美東")],
    "tw": [("^TWII", "發行量加權指數", "TWII", "09:00–13:30 台北"), ("2330.TW", "台積電", "2330", "09:00–13:30 台北"), ("2454.TW", "聯發科", "2454", "09:00–13:30 台北")],
}
GROUPS_US = {"^VIX": "總體", "^TNX": "總體"}
SESSION_LABEL = {"us": "美東 16:00 收盤", "tw": "台北 13:30 收盤集合競價（13:33 定盤確認）"}
MARKET_NAME = {"us": "美股", "tw": "台股"}


def group_of(market, sym):
    if market == "us":
        return GROUPS_US.get(sym, "指數" if sym.startswith("^") else "AI／個股")
    if sym == "^TWII":
        return "指數"
    if sym.startswith("00"):
        return "ETF"
    return "權值股"


def build_blocks(market, quotes):
    # .cards flex wrapper is Python's job, never the LLM's — keeps the
    # horizontal card layout deterministic across runs.
    cards = '<div class="cards">\n%s\n  </div>' % cards_html(
        [(label, disp, quotes[sym]) for sym, label, disp in CARDS_SPECS[market] if sym in quotes])
    rows = []
    for sym, v in quotes.items():
        if "error" in v:
            continue
        if sym.startswith("^") and v.get("volume") == 0:
            v = dict(v, volume=None)  # index quotes carry no volume; show —
        rows.append((v.get("name") or sym, sym.split(".")[0] if not sym.startswith("^") else sym.replace("^", ""),
                     group_of(market, sym), v, ""))
    src_note = ("資料：證交所 FMTQIK／MIS 定案數據，走勢圖 Yahoo Finance" if market == "tw"
                else "資料：Yahoo Finance 定案數據")
    table = quote_table_html(rows, "表 1：%s主要指數與標的收盤行情（紅漲／綠跌；%s）" % (MARKET_NAME[market], src_note),
                             extra_col="成交量")
    sparks = "\n".join(
        sparkline_html(quotes[sym], label, disp, sess)
        for sym, label, disp, sess in SPARK_SPECS[market] if sym in quotes and "error" not in quotes[sym])
    return cards, table, '<div class="sparks">\n%s\n    </div>' % sparks


def data_digest(market, d):
    lines = []
    for sym, v in d["quotes"].items():
        if "error" in v:
            lines.append("%s %s 抓取失敗" % (sym, v.get("name", "")))
            continue
        vol = ("{:,}".format(int(v["volume"])) if v.get("volume") not in (None, "None") else "—")
        lines.append("%s %s：收 %s（%+.2f%%，%+.2f）全日 %s–%s 量 %s" % (
            sym, v.get("name", ""), fmt(v.get("close")), v.get("pct") or 0, v.get("chg") or 0,
            fmt(v.get("day_low")), fmt(v.get("day_high")), vol))
    main_sym = "^GSPC" if market == "us" else "^TWII"
    daily = (d["quotes"].get(main_sym) or {}).get("daily") or []
    if daily:
        lines.append("近月日K（%s）：%s" % (main_sym, " → ".join("%s %s" % (x["date"][5:], fmt(x["close"])) for x in daily[-8:])))
    if market == "tw":
        fq = d.get("fmtqik") or {}
        if fq.get("today"):
            t = fq["today"]
            lines.append("FMTQIK 今日定案：成交值約 %s 億元、加權指數 %s（%s）" % (
                ("{:,.0f}".format(t["turnover_ntd_1e8"]) if t.get("turnover_ntd_1e8") else "待確認"),
                fmt(t.get("index_close")), t.get("change")))
        else:
            month = fq.get("month") or []
            tail = "、".join("%s %s億" % (r["date"][5:], "{:,.0f}".format(r["turnover_ntd_1e8"])) for r in month[-4:] if r.get("turnover_ntd_1e8"))
            lines.append("FMTQIK 今日列尚未發布（官方日統計晚間更新）；近幾日成交值：%s" % (tail or "無資料"))
    return "\n".join(lines)


def news_digest(news, max_news):
    items = news.get("items") or []
    if not items:
        return "（本次未取得新聞——收盤解讀請以數據結構分析為主，並在資料來源注明）"
    return "\n".join("- %s（%s，%s）" % (i["title"], i.get("source") or "?", i.get("published") or "時間不明")
                     for i in items[:max_news])


SYSTEM_TMPL = """你是「經濟循環研究 · 收盤快報」的資深撰述者，用繁體中文寫每日%(market)s收盤報告。
嚴格遵循以下系列脈絡與寫作紀律：

%(context)s

【本次輸出規則】
- 只輸出一個 JSON 物件，不要 markdown 圍欄。Schema:
  {"title": "...", "meta_line": "...", "summary_html": "...", "sections": [{"heading": "...", "body_html": "..."}], "footer_note": "...", "open_items": [{"topic": "...", "text": "..."}], "resolutions": [{"id": "...", "text": "..."}]}
- title：%(market)s收盤報告的主題式標題（不含日期）。要抓當日故事，不要「大漲大跌」這種空泛詞。
- meta_line：一行，含 收盤定案日期（%(session)s）與 資料來源：官方定案數據（美股＝Yahoo Finance；台股＝證交所 FMTQIK／MIS，走勢圖 Yahoo Finance）＋當日新聞彙整。
- summary_html：以 <b>一句話結論：</b> 開頭，100–250 字，量價＋事件＋結構三要素；可用 <b class="up">／<b class="down">。
- sections 至少五節，依序：
  1.「一、收盤快照」body_html 必須剛好包含兩行佔位符：__CARDS__ 與 __TABLE__（各自獨立一行，__CARDS__ 會被替換成完整的三格卡片區塊、__TABLE__ 會被替換成完整表格＋表註——不要用自己的 div 包住佔位符；佔位符前可加一句導言）。
  2.「二、全日走勢」body_html 必須包含 __SPARKS__ 一行（可加一段走勢解讀文字）。
  3.「三、收盤解讀：…」當日主題式小標；2–4 個 <li>，每個以 <b>粗體重點</b> 開頭；講為什麼與結構，引用新聞要指明媒體名；數字一律用【市場數據】區的值。
  4. 依當日情況 0–2 個進階節（名家框架印證／政策與事件／對另一市場的連動／階段防線——防線表用 <table class="stage">，區間照 CONTEXT，但「現況」欄依當日數據重算）。
  5. 「觀察清單」：<ol>，4–7 個下一交易日具體檢驗點（指數關卡、事件日、待發布數據）。%(watch_extra)s
  6. 「資料來源」：<ul class="src">，逐條列出（Yahoo Finance 定案數據；新聞引用列媒體名＋日期，不編造連結；CONTEXT 引用註明「系列脈絡」）。
- 【系列記憶】使用規則（user 訊息末附狀態檔摘要；標籤：[待查]＝未結案追蹤項、[結論]＝已結案結論、[逾時結案]＝追蹤逾時、[常規]＝近期市場事實）：
  - 今日數據或事件已能回答某 [待查] 項時，將其 id 原樣填入 resolutions 的 "id"，"text" 寫 1–2 句結論；答不了就不要列。
  - [逾時結案] 項必須在「觀察清單」末尾加一條 <li>追蹤逾時結案：…（id）</li>。
  - open_items：0–4 個本日新產生、值得後續交易日追蹤的具體問題（事件日、待發布數據、待驗證論點）；topic 用短代號（如 nvda、fed、tw-t86）；不要把常規事實列入。
- 誠實條款：推測標明「推論，非實證」；不虛構任何數字、人名引述或媒體；新聞沒提的因果不要硬套。
- footer_note：一句話（例：本報告為 N 收盤定案數據；不構成投資建議），python 會再附上免責與生成時間。"""

WATCH_EXTRA = {
    "tw": "今晚 ~20:00 證交所三大法人（T86）數據是必列觀察點（13:43 時尚未發布，報告內嚴禁填入當日法人數字）。",
    "us": "",
}


def call_llm(token, model, system, user, timeout=300):
    """Chat completion handling BOTH SSE streaming and plain-JSON responses
    (some gateways ignore the stream flag). Raises with a body preview when
    nothing usable comes back. Returns (parsed_json_content, usage)."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer %s" % token,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "market-brief-pipeline",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "ignore")

    def _strip_fence(s):
        return re.sub(r"^```(json)?|```$", "", s.strip(), flags=re.M).strip()

    content, usage, reasoning_len = "", {}, 0
    if "data:" in raw:
        # SSE path
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                raise RuntimeError("API error in stream: %s" % json.dumps(chunk["error"], ensure_ascii=False)[:300])
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    content += delta["content"]
                if delta.get("reasoning_content"):
                    reasoning_len += len(delta["reasoning_content"])
    else:
        # plain JSON path
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError("unparseable response, first 300 chars: %r" % raw[:300])
        if out.get("error"):
            raise RuntimeError("API error: %s" % json.dumps(out["error"], ensure_ascii=False)[:300])
        usage = out.get("usage", {})
        msg = ((out.get("choices") or [{}])[0].get("message") or {})
        content = msg.get("content") or ""
        reasoning_len = len(msg.get("reasoning_content") or "")

    if not content:
        raise RuntimeError("no content in response (reasoning_only=%d chars, completion_tokens=%s), first 300 chars: %r" % (
            reasoning_len, usage.get("completion_tokens"), raw[:300]))
    return json.loads(_strip_fence(content)), usage


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    market, data_path, news_path = args[0], args[1], args[2]
    out_dir = None
    dump_prompt = None
    model = DEFAULT_MODEL
    max_news = 18
    for i, a in enumerate(sys.argv):
        if a == "--out-dir" and i + 1 < len(sys.argv):
            out_dir = sys.argv[i + 1]
        if a == "--dump-prompt" and i + 1 < len(sys.argv):
            dump_prompt = sys.argv[i + 1]
        if a == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
        if a == "--max-news" and i + 1 < len(sys.argv):
            max_news = int(sys.argv[i + 1])
    token = os.environ.get("LLM_API_TOKEN", "").strip()
    if not token:
        print(json.dumps({"ok": False, "error": "LLM_API_TOKEN not set or empty"}))
        sys.exit(1)

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    with open(news_path, encoding="utf-8") as f:
        news = json.load(f)
    with open(os.path.join(ROOT, "CONTEXT.md"), encoding="utf-8") as f:
        context = f.read()
    with open(os.path.join(ROOT, "templates", "report_base.html"), encoding="utf-8") as f:
        template = f.read()

    session_date = data["session_date"]
    # Series memory: expire dead threads first (write=False keeps --dump-prompt
    # read-only), then inject the bounded digest into the prompt.
    state_path = STATE_PATH
    latest, newly_expired = prune_state(state_path, write=not dump_prompt)
    digest_text = state_digest(latest)
    cards, table, sparks = build_blocks(market, data["quotes"])

    system = SYSTEM_TMPL % {"market": MARKET_NAME[market], "session": SESSION_LABEL[market],
                            "context": context, "watch_extra": WATCH_EXTRA[market]}
    user = ("【市場數據】%s 交易日 %s\n%s\n\n【當日新聞彙整（Google/Bing News，已依相關度排序）】\n%s\n\n"
            "【系列記憶（狀態檔摘要；[待查] 項的 id 供結案引用）】\n%s\n\n請產出 JSON。" % (
                MARKET_NAME[market], session_date, data_digest(market, data),
                news_digest(news, max_news), digest_text))

    if dump_prompt:
        os.makedirs(os.path.dirname(os.path.abspath(dump_prompt)) or ".", exist_ok=True)
        with open(dump_prompt, "w", encoding="utf-8", newline="\n") as f:
            f.write("=== SYSTEM ===\n%s\n\n=== USER ===\n%s\n" % (system, user))
        print(json.dumps({"ok": True, "dump_prompt": dump_prompt,
                          "state_expired_marked": len(newly_expired)}, ensure_ascii=False))
        return

    result, usage, last_err = None, None, None
    for attempt in (1, 2):
        try:
            t0 = time.time()
            result, usage = call_llm(token, model, system, user)
            break
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s: %s" % (e.code, e.read(200).decode("utf-8", "ignore"))
            if e.code == 429 and attempt == 1:
                time.sleep(20)
                continue
            break
        except json.JSONDecodeError as e:
            last_err = "model output not valid JSON (%s)" % e
            if attempt == 1:
                time.sleep(5)
            continue
        except Exception as e:  # noqa: BLE001
            last_err = "%s: %s" % (type(e).__name__, str(e)[:200])
            if attempt == 1:
                time.sleep(5)
    if result is None:
        print(json.dumps({"ok": False, "error": "LLM call failed: %s" % last_err}, ensure_ascii=False))
        sys.exit(1)

    sections_html = []
    for i, sec in enumerate(result["sections"]):
        sections_html.append('<section%s>\n  <h2>%s</h2>\n  %s\n</section>' % (
            ' class="first"' if i == 0 else "", sec["heading"], (sec.get("body_html") or "").strip()))
    sections_html = "\n\n".join(sections_html)

    gen_time = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 8 * 3600))
    html = (template
            .replace("__TITLE_TAG__", "%s（%s）" % (result["title"], session_date))
            .replace("__TITLE__", result["title"])
            .replace("__META_LINE__", result["meta_line"])
            .replace("__SUMMARY_HTML__", (result.get("summary_html") or "").strip())
            .replace("__SECTIONS_HTML__", sections_html
                     .replace("__CARDS__", cards)
                     .replace("__TABLE__", table)
                     .replace("__SPARKS__", sparks))
            .replace("__FOOTER_HTML__", "%s<br/>本報告不構成投資建議；由雲端管線自動生成（GitHub Actions＋%s），生成時間：台北時間 %s。" % (
                result.get("footer_note", ""), model.split("/")[-1], gen_time)))

    if out_dir:
        dst = os.path.join(out_dir, "index.html")
    else:
        dst = os.path.join(ROOT, "reports", market, session_date, "index.html")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)

    # State write-back: routine facts + report brief are deterministic; the
    # LLM contributes open_items (new questions) and resolutions (conclusions
    # for existing [待查] ids). Best-effort — a state failure never kills the
    # report that was already written.
    warnings, n_added = [], 0
    try:
        base_ids = tuple(latest.keys())
        new_recs = make_routine_facts(market, data, existing_ids=base_ids)
        new_recs += make_report_brief(market, result, session_date,
                                      existing_ids=base_ids + tuple(r["id"] for r in new_recs))

        def _ids():
            return base_ids + tuple(r["id"] for r in new_recs)

        for item in (result.get("open_items") or [])[:6]:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            topic = ((item.get("topic") or "general").strip()[:40]) or "general"
            new_recs.append(make_record("open", topic, text[:200], existing_ids=_ids()))
        for res in (result.get("resolutions") or [])[:6]:
            rid = (res.get("id") or "").strip()
            text = (res.get("text") or "").strip()
            if not rid or not text:
                continue
            tgt = latest.get(rid)
            if not tgt or tgt.get("status") != "open":
                warnings.append("resolution skipped (unknown/closed id %s)" % rid)
                continue
            rec = make_record("resolved", tgt.get("topic", "general"),
                              text if text.startswith("結論") else "結論：" + text, existing_ids=_ids())
            rec["id"] = rid
            new_recs.append(rec)
        n_added = append_records(state_path, new_recs)
    except Exception as e:  # noqa: BLE001
        warnings.append("state update failed: %s: %s" % (type(e).__name__, str(e)[:150]))

    verdict = {"ok": True, "market": market, "session_date": session_date, "title": result["title"],
               "output": dst, "model": model, "tokens": usage,
               "state": {"added": n_added, "expired_marked": len(newly_expired)}}
    if warnings:
        verdict["warnings"] = warnings
    print(json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()

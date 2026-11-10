# -*- coding: utf-8 -*-
"""Cloud report generator: GitHub Models writes the narrative, Python assembles.

Pipeline: data json + news json + CONTEXT.md + report_helpers blocks
          → one LLM call returning strict JSON (title / meta / summary / sections)
          → deterministic HTML assembly from templates/report_base.html.

Usage:
    python scripts/gen_report_cloud.py <market us|tw> <data.json> <news.json> \
        [--out-dir DIR] [--model MODEL] [--max-news 18]

Env: LLM_API_TOKEN (API key for the OpenAI-compatible endpoint), optional
LLM_BASE_URL / LLM_MODEL (defaults: Zhipu bigmodel.cn, glm-4.6). Default output
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# OpenAI-compatible endpoint; default is Zhipu bigmodel.cn (GLM). Override via env.
ENDPOINT = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "glm-5.3-flash")

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
    cards = cards_html([(label, disp, quotes[sym]) for sym, label, disp in CARDS_SPECS[market] if sym in quotes])
    rows = [(v.get("name") or sym, sym.split(".")[0] if not sym.startswith("^") else sym.replace("^", ""),
            group_of(market, sym), v, "") for sym, v in quotes.items() if "error" not in v]
    table = quote_table_html(rows, "表 1：%s主要指數與標的收盤行情（紅漲／綠跌；資料：Yahoo Finance 定案數據）" % MARKET_NAME[market],
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
  {"title": "...", "meta_line": "...", "summary_html": "...", "sections": [{"heading": "...", "body_html": "..."}], "footer_note": "..."}
- title：%(market)s收盤報告的主題式標題（不含日期）。要抓當日故事，不要「大漲大跌」這種空泛詞。
- meta_line：一行，含 收盤定案日期（%(session)s）與 資料來源：Yahoo Finance 定案數據＋當日新聞彙整。
- summary_html：以 <b>一句話結論：</b> 開頭，100–250 字，量價＋事件＋結構三要素；可用 <b class="up">／<b class="down">。
- sections 至少五節，依序：
  1.「一、收盤快照」body_html 必須剛好包含兩行佔位符：__CARDS__ 與 __TABLE__（各自一行，前後可加一句導言與表註 <p class="caption">）。
  2.「二、全日走勢」body_html 必須包含 __SPARKS__ 一行（可加一段走勢解讀文字）。
  3.「三、收盤解讀：…」當日主題式小標；2–4 個 <li>，每個以 <b>粗體重點</b> 開頭；講為什麼與結構，引用新聞要指明媒體名；數字一律用【市場數據】區的值。
  4. 依當日情況 0–2 個進階節（名家框架印證／政策與事件／對另一市場的連動／階段防線——防線表用 <table class="stage">，區間照 CONTEXT，但「現況」欄依當日數據重算）。
  5. 「觀察清單」：<ol>，4–7 個下一交易日具體檢驗點（指數關卡、事件日、待發布數據）。%(watch_extra)s
  6. 「資料來源」：<ul class="src">，逐條列出（Yahoo Finance 定案數據；新聞引用列媒體名＋日期，不編造連結；CONTEXT 引用註明「系列脈絡」）。
- 誠實條款：推測標明「推論，非實證」；不虛構任何數字、人名引述或媒體；新聞沒提的因果不要硬套。
- footer_note：一句話（例：本報告為 N 收盤定案數據；不構成投資建議），python 會再附上免責與生成時間。"""

WATCH_EXTRA = {
    "tw": "今晚 ~20:00 證交所三大法人（T86）數據是必列觀察點（13:43 時尚未發布，報告內嚴禁填入當日法人數字）。",
    "us": "",
}


def call_llm(token, model, system, user, timeout=150):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer %s" % token,
        "Content-Type": "application/json",
        "User-Agent": "market-brief-pipeline",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    content = out["choices"][0]["message"]["content"]
    usage = out.get("usage", {})
    content = re.sub(r"^```(json)?|```$", "", content.strip(), flags=re.M).strip()
    return json.loads(content), usage


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    market, data_path, news_path = args[0], args[1], args[2]
    out_dir = None
    model = DEFAULT_MODEL
    max_news = 18
    for i, a in enumerate(sys.argv):
        if a == "--out-dir" and i + 1 < len(sys.argv):
            out_dir = sys.argv[i + 1]
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
    cards, table, sparks = build_blocks(market, data["quotes"])

    system = SYSTEM_TMPL % {"market": MARKET_NAME[market], "session": SESSION_LABEL[market],
                            "context": context, "watch_extra": WATCH_EXTRA[market]}
    user = "【市場數據】%s 交易日 %s\n%s\n\n【當日新聞彙整（Google/Bing News，已依相關度排序）】\n%s\n\n請產出 JSON。" % (
        MARKET_NAME[market], session_date, data_digest(market, data), news_digest(news, max_news))

    result, usage, last_err = None, None, None
    for attempt in (1, 2):
        try:
            result, usage = call_llm(token, model, system, user)
            break
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s: %s" % (e.code, e.read(200).decode("utf-8", "ignore"))
            if e.code == 429 and attempt == 1:
                time.sleep(20)
                continue
            break
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:200]
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
    print(json.dumps({"ok": True, "market": market, "session_date": session_date, "title": result["title"],
                      "output": dst, "model": model, "tokens": usage}, ensure_ascii=False))


if __name__ == "__main__":
    main()

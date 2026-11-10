# -*- coding: utf-8 -*-
"""Shared HTML block generators for daily reports.

Adapted from the proven html_build/tw_gen_report.py and gen_report.py so the
visual language stays identical across all reports. Import from a one-off
daily generator script, e.g.:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from report_helpers import load_data, cards_html, quote_table_html, sparkline_html

Records are the uniform per-symbol dicts written by fetch_us.py / fetch_tw.py:
    {name, close, prev, chg, pct, day_low, day_high, volume, series, daily}

Colour convention (Taiwan): red = up, green = down — same as every existing
report in this series.
"""
import json

UP, DOWN, FLAT = "#c0392b", "#1e7a46", "#757c7f"


def pct_col(p):
    return UP if (p or 0) > 0.05 else (DOWN if (p or 0) < -0.05 else FLAT)


def fmt(v):
    return "{:,.2f}".format(v) if v is not None else "—"


def fmt_vol(v):
    return "{:,}".format(int(v)) if v not in (None, "None") else "—"


def load_data(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d["session_date"], d["quotes"]


def cards_html(items):
    """items: list of (label, sym, record)."""
    cells = []
    for label, sym, rec in items:
        c = pct_col(rec.get("pct"))
        rng = "全日 %s – %s" % (fmt(rec.get("day_low")), fmt(rec.get("day_high")))
        if rec.get("day_low") is None:
            rng = ""
        cells.append("""
      <div class="card">
        <div class="card-label">%s <span class="card-sym">%s</span></div>
        <div class="card-num">%s</div>
        <div class="card-chg" style="color:%s">%+.2f%%　%+.2f</div>
        <div class="card-range">%s</div>
      </div>""" % (label, sym, fmt(rec.get("close")), c,
                   rec.get("pct") or 0, rec.get("chg") or 0, rng))
    return "\n".join(cells)


def quote_table_html(rows, caption, extra_col=None):
    """rows: list of (name, sym, group, record, extra_note).
    extra_col: optional header for a trailing volume column; when given the
    cell shows the record volume and extra_note annotates inline after pct
    (e.g. 漲停). Without it extra_note still annotates inline and no trailing
    column is emitted."""
    has_extra = extra_col is not None
    head = "<tr><th>標的</th><th>類別</th><th>收盤</th><th>漲跌幅</th><th>漲跌</th><th>全日區間</th>%s</tr>" % (
        "<th>%s</th>" % extra_col if has_extra else "")
    body = []
    for name, sym, group, rec, extra in rows:
        c = pct_col(rec.get("pct"))
        inline = ("　" + extra) if extra else ""
        body.append("""
      <tr>
        <td class="c-name">%s<span class="c-sym">%s</span></td>
        <td class="c-group">%s</td>
        <td class="c-num">%s</td>
        <td class="c-num" style="color:%s"><span style="white-space:nowrap"><b>%+.2f%%</b>%s</span></td>
        <td class="c-num" style="color:%s">%+.2f</td>
        <td class="c-num">%s – %s</td>%s
      </tr>""" % (name, sym, group, fmt(rec.get("close")), c, rec.get("pct") or 0,
                  inline, c, rec.get("chg") or 0, fmt(rec.get("day_low")), fmt(rec.get("day_high")),
                  ('\n        <td class="c-num">%s</td>' % fmt_vol(rec.get("volume"))) if has_extra else ""))
    return """
  <table>
    <thead>%s</thead>
    <tbody>%s
    </tbody>
  </table>
  <p class="caption">%s</p>""" % (head, "\n".join(body), caption)


def sparkline_html(rec, label, sym, session_label, anchor=None):
    """SVG day-trace from the 5m close series; red/green by day change.
    anchor: optional (open, close) official auction prices to prepend/append."""
    s = [round(v, 2) for v in (rec.get("series") or []) if v is not None]
    if anchor:
        o, c = anchor
        s = [o] + s + [c]
    if len(s) < 3:
        return ""
    w, h, pad = 700, 120, 10
    mn, mx = min(s), max(s)
    rng = (mx - mn) or 1.0
    n = len(s)
    xs = [pad + i * (w - 2 * pad) / (n - 1) for i in range(n)]
    ys = [h - pad - (x - mn) / rng * (h - 2 * pad) for x in s]
    pts = " ".join("%.1f,%.1f" % (a, b) for a, b in zip(xs, ys))
    area = "M %.1f %.1f L %s L %.1f %.1f Z" % (xs[0], h - pad, pts, xs[-1], h - pad)
    col = pct_col(rec.get("pct"))
    foot = "%s · 全日區間 %s – %s" % (session_label, fmt(rec.get("day_low")), fmt(rec.get("day_high")))
    return """
    <div class="spark-card">
      <div class="spark-head"><span class="spark-title">%s <span class="card-sym">%s</span></span>
        <span class="spark-now" style="color:%s">收 %s　<b>%+.2f%%</b></span></div>
      <svg viewBox="0 0 %d %d" preserveAspectRatio="none" role="img" aria-label="%s 全日走勢">
        <path d="%s" fill="rgba(73,101,117,0.10)" stroke="none"/>
        <polyline points="%s" fill="none" stroke="#496573" stroke-width="2" stroke-linejoin="round"/>
        <circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>
        <text x="%d" y="%d" class="svghi">%s</text>
        <text x="%d" y="%d" class="svglo">%s</text>
      </svg>
      <div class="spark-foot">%s</div>
    </div>""" % (label, sym, col, fmt(rec.get("close")), rec.get("pct") or 0,
                 w, h, label, area, pts, xs[-1], ys[-1], col,
                 pad, 13, fmt(mx), pad, h - 2, fmt(mn), foot)

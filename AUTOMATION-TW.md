# 台股盤後報告 — 排程執行手冊（Runbook）

> 本檔案供 ZCode 排程自動化於**無人值守**時遵循。你（執行中的代理）沒有對話歷史可依賴，
> 一切以本檔案與 repo 內檔案為準。逐步執行，不可跳步。

- **排程**：台北時間週一至週五 13:40（13:30 收盤、13:33 定盤後，資料已定案）
- **Repo**：`C:\Users\charl\Documents\My Ideas\股市報告\market-brief`（下稱 REPO）
- **產出**：`reports/tw/<日期>/index.html` ＋ 更新 `manifest.json` ＋ push 至 GitHub（Pages 自動發布）

## 第 0 步：環境

```bash
cd "C:\Users\charl\Documents\My Ideas\股市報告\market-brief"
git status --short   # 應為乾淨；若有髒檔，先 STOP 並在最終報告說明（可能是上次執行中斷）
```

Python 用系統 `python`（3.14，僅 stdlib 即可）。

## 第 1 步：抓資料＋交易日守衛

```bash
python scripts/fetch_tw.py
```

stdout 最後一行是 JSON verdict，依此分流：

| verdict | 動作 |
|---|---|
| `ok=false` 且 reason 含 `not_trading_day` | 台股假日（國定假日自動被守衛涵蓋）。**靜默結束**。 |
| `ok=false`（其他原因） | 資料來源異常。**不產報告、不 push**，最終報告說明原因。 |
| `ok=true` 且 `report_exists=true` | 今日報告已存在（重跑）。**靜默結束**。 |
| `ok=true` 且 `report_exists=false` | 通過，記下 `session_date`（=今天）與 `output`，繼續第 2 步。 |

**資料口徑須知（13:40 時點）**：
- 收盤價、漲跌幅、全日區間、成交量、5 分鐘序列：已定案，可直接引用。
- `fmtqik.today` 為 null 時＝證交所日統計尚未發布：成交值若要引用，標註「初步值，待官方日統計確認」，否則省略。
- **三大法人買賣超（T86）當日傍晚才發布**：13:40 報告「禁止」填入當日法人數據或用公股行庫等分點數據冒充——一律列入「觀察清單」（今晚 ~20:00 公布後的檢驗點）。**前一交易日**的法人數據可作為背景引用（來源標明）。

## 第 2 步：當日市場新聞（盡力而為，非必要條件）

用 WebSearch 檢索 2–4 個查詢，例如：`台股 收盤 <月/日>`、`台股加權指數 今天 收盤 <date>`、
當日重大事件（政策、外資、財報、國際連動）加查專題。

- 另外讀取**前一夜美股**：`reports/us/` 下最新一篇收盤報告（存在時），其「對台股的連動」章節是今日開盤背景的直接材料。
- 搜尋失敗：報告照常產出（純數據解讀），「資料來源」註明。

## 第 3 步：生成報告 HTML

寫一支一次性腳本 `scripts/gen_tw_<YYYYMMDD>.py`（YYYYMMDD 為 session_date），結構比照
`scripts/report_helpers.py` docstring 範例：載入 `data/tw_<YYYYMMDD>.json`、
`templates/report_base.html`，用 helpers 產生數據區塊，自己填敘事，輸出到
`reports/tw/<session_date>/index.html`。生成後執行該腳本。

**報告結構（章節順序）**：
1. 收盤快照 — cards（加權指數／台積電／0050 或當日焦點）＋ quote table（紅漲綠跌）
2. 全日走勢 — sparkline（加權指數＋台積電＋當日焦點股；session_label 用 `09:00–13:30 台北`）
3. 收盤解讀 — 2–4 條 <li>；量價結構（跳空、振幅、尾盤型態）＋與美股前夜／政策背景的連動；數據從 JSON 取，**禁止憑記憶填數字**
4. （可選）政策／事件專節 — 有重大政策（護盤、限空令、選舉等）或國際事件時
5. （可選）階段防線表 — 引用既有系列的名家觀點防線表（見 `reports/tw/2026-11-09/index.html` 表 2；指數位置重算，其餘保持彙整口径並標明非投資建議）
6. 觀察清單 — <ol>：明早美股／今晚法人數據／技術關卡／近期事件日
7. 資料來源 — <ul class="src">

**必守規則**：
- 標題 `<title>`：`台股收盤報告：<當日主題>（<session_date>）`；h1 同但不含日期括號。
- `.summary` 以 `<b>一句話結論：</b>` 開頭，100–250 字。
- header `.meta`：`收盤定案：<session_date>（週幾）13:30 收盤集合競價（定盤數據 13:33 確認）· 資料來源：Yahoo Finance（證交所報價同步）＋盤後新聞`
- 漲停股標注（pct ≥ +9.8% 通常為漲停，仍以當日實際涨跌停制度 10% 判斷，標「漲停」於表格外註）。
- 推測性內容必須標明；不可虛構任何數字、引述或來源。
- footer 免責聲明＋生成時間（台北時間）。
- 水準基準：`reports/tw/2026-11-09/index.html`。

## 第 4 步：更新索引

```bash
python scripts/update_manifest.py 150
```

（同美股 runbook；可再手編 manifest summary 使其更精準。）

## 第 5 步：提交並推送

```bash
git add reports data manifest.json scripts/gen_tw_<YYYYMMDD>.py
git diff --cached --stat    # 變更行數應與預期相符；異常爆量＝行尾問題，先還原再查
git commit -m "docs(tw): add TW market report <session_date>"
git push origin main
```

- Commit message 英文、conventional；每日報告不 bump 版號。
- push 失敗重試一次；再失敗則如實回報「已生成未推送」。

## 第 6 步：最終報告

回報：session_date、報告標題、commit hash、推送結果（與一句話市場摘要）。失敗如實回報。

## 禁止事項

- 不得修改既有歷史報告；不得改基礎設施檔案（fetch/update scripts、templates、index.html、排程）。
- 不得虛構或預填當日尚未發布的官方統計（三大法人、成交值日統計）。
- 不得 push 到 main 以外、不得 force push。
- 需要改基礎檔案才能完成時：STOP，最終報告說明建議，等人工處理。

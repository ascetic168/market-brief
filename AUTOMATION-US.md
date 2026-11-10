# 美股盤後報告 — 排程執行手冊（Runbook）

> 本檔案供 ZCode 排程自動化於**無人值守**時遵循。你（執行中的代理）沒有對話歷史可依賴，
> 一切以本檔案與 repo 內檔案為準。逐步執行，不可跳步。

- **排程**：台北時間週二至週六 05:30（涵蓋美股週一至週五收盤；冬令收盤=台北 05:00、夏令=04:00，05:30 皆為收盤定案後）
- **Repo**：`C:\Users\charl\Documents\My Ideas\股市報告\market-brief`（下稱 REPO）
- **產出**：`reports/us/<美股交易日>/index.html` ＋ 更新 `manifest.json` ＋ push 至 GitHub（Pages 自動發布）

## 第 0 步：環境

```bash
cd "C:\Users\charl\Documents\My Ideas\股市報告\market-brief"
git status --short   # 應為乾淨；若有髒檔，先 STOP 並在最終報告說明（可能是上次執行中斷）
```

Python 用系統 `python`（3.14，僅 stdlib 即可）。

## 第 1 步：抓資料＋交易日守衛

```bash
python scripts/fetch_us.py
```

stdout 最後一行是 JSON verdict，依此分流：

| verdict | 動作 |
|---|---|
| `ok=false` | 資料來源異常。**不產報告、不 push**。最終報告說明原因即結束。 |
| `ok=true` 且 `report_exists=true` | 該美股交易日已有報告（假日／重跑皆屬此類）。**靜默結束**，最終報告一句話帶過即可。 |
| `ok=true` 且 `report_exists=false` | 通過，記下 `session_date` 與 `output`，繼續第 2 步。 |

## 第 2 步：當日市場新聞（盡力而為，非必要條件）

用 WebSearch 檢索 2–4 個查詢，例如：
`US stock market close <Month Day, Year> S&P 500 Nasdaq`、`<session_date> stock market news`、
當日有大事件時加查該事件（個股財報、Fed、地緣等）。

- 目的：讓「收盤解讀」章節的敘事有事實根據（漲跌原因、關鍵新聞、名家/機構說法）。
- 搜尋失敗或無結果：報告仍照常產出（純數據解讀），並在「資料來源」註明當日未取得新聞補充。
- 引用的每個事實都要有來源；新聞連結列進「資料來源」章節。

## 第 3 步：生成報告 HTML

寫一支一次性腳本 `scripts/gen_us_<YYYYMMDD>.py`（YYYYMMDD 為 session_date），結構比照
`scripts/report_helpers.py` 的 docstring 範例：載入 `data/us_<YYYYMMDD>.json`、
`templates/report_base.html`，用 helpers 產生數據區塊，自己填敘事，輸出到
`reports/us/<session_date>/index.html`。生成後執行該腳本。

**報告結構（章節順序）**：
1. 收盤快照 — cards（S&P 500／Nasdaq／費半 或當日焦點）＋全標的 quote table（顏色：紅漲綠跌）
2. 全日走勢 — sparkline（指數 2–3 個＋當日焦點個股）
3. 收盤解讀 — 2–4 條 <li>，每條有 <b>粗體重點</b>；引用第 2 步新聞；數據從 JSON 取，**禁止憑記憶填數字**
4. （可選）名家框架印證／對台股連動 — 延續既有系列報告的框架（Ray Dalio、Grantham、Burry 等對 AI 泡沫的觀點；台股連動引用 `reports/tw/` 最近的台股報告）
5. 觀察清單 — <ol>，下一交易日的具體檢驗點（含指數關卡、財報、事件日）
6. 資料來源 — <ul class="src">，條列（Yahoo Finance＋每則新聞來源與連結）

**必守規則**：
- 標題 `<title>`：`美股收盤報告：<當日主題>（<session_date>）`；h1 同但不含日期括號。
- `.summary` 區塊以 `<b>一句話結論：</b>` 開頭，100–250 字，量價＋事件＋結構三要素。
- header `.meta`：`收盤定案：<session_date>（週幾）美東 16:00 收盤（台北時間 <月/日> 05:00 或 04:00 依冬夏令）· 資料來源：Yahoo Finance 收盤數據`
- 推測性內容必須標明（如「推論，非實證」）；不可虛構任何數字、引述或來源。
- footer 保留免責聲明（不構成投資建議）＋生成時間（台北時間）。
- 所有數字與 JSON 一致；round 規則沿用 helpers。
- 既有系列報告風格參考：`reports/us/2026-11-09/index.html`（水準基準——新報告至少要有一條有洞見的解讀與誠實的邊界聲明，不是數據複誦）。

## 第 4 步：更新索引

```bash
python scripts/update_manifest.py 150
```

（新報告的 title 自動取自 <title>；summary 自動取 .summary 前 150 字。若想要更精準的摘要，
可直接編輯 manifest.json 中該條目的 summary — 內容需與報告一致。）

## 第 5 步：提交並推送

```bash
git add reports data manifest.json scripts/gen_us_<YYYYMMDD>.py
git diff --cached --stat    # 變更行數應與預期相符（新報告 1 檔＋data 1 檔＋manifest 少量行）；若異常爆量，檢查行尾問題（unix2dos/dos2unix）
git commit -m "docs(us): add US market report <session_date>"
git push origin main
```

- Commit message 一律英文、conventional 格式；**每日報告不 bump 版號**。
- push 失敗（網路等）：重試一次；再失敗則在最終報告明確說明「報告已生成但未推送」。

## 第 6 步：最終報告

回報：session_date、報告標題、commit hash、推送結果（與一句話市場摘要）。
任何一步失敗都要如實回報，不得掩蓋或部分推送。

## 禁止事項

- 不得修改既有歷史報告（`reports/` 下已存在的目錄）。
- 不得 push 到 main 以外的分支、不得 force push。
- 不得變更排程設定或本 runbook 以外的基礎設施檔案（scripts 的 fetch/update、templates、index.html）。
- 若判斷需要修改上述基礎檔案才能完成任務：STOP，在最終報告說明建議，等人工處理。

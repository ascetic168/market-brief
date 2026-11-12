# 自動化架構（AUTOMATION）

> 本 repo 的報告由 **GitHub Actions 雲端管線**全自動產出，不依賴任何本地機器。
> 本文件描述架構、排程、秘鑰與維運要點。

## 排程與觸發

| Workflow | GitHub 排程（備用，UTC） | 台北時間 | 涵蓋 |
|---|---|---|---|
| [tw-report.yml](.github/workflows/tw-report.yml) | `43 5 * * 1-5` | 週一至週五 13:43 | 台股 13:30 收盤＋13:33 定盤後 |
| [us-report.yml](.github/workflows/us-report.yml) | `33 21 * * 2-6` | 週二至週六 05:33 | 美股收盤（冬令台北 05:00／夏令 04:00 之後） |
| [tw-chips.yml](.github/workflows/tw-chips.yml) | `50 13 * * 1-5` | 週一至週五 21:50 | 台股籌碼（三大法人＋資券）靜默寫入系列記憶 |

- **主要觸發**：外部 cron-job.org → `workflow_dispatch` API（2026-11-12 起運作；
  GitHub schedule 降為每日一次備用，0.2.1 的 +30 分 catch-up 已移除——
  冪等閘門〔時間守衛＋report_exists〕使重複觸發無害，一次備用即足）。
- GitHub 官方提醒尖峰時刻（整點）排程可能延遲數分鐘至更久，故備用排程刻意避開整點。
- 兩支 workflow 皆支援 `workflow_dispatch` 手動觸發，附：

- **dry_run**：只抓資料＋新聞、不呼叫 LLM、不 push（驗證 runner 連線用）
- **force**：繞過台北時間守衛（除錯用；正式排程不需要）

## 每日流程（兩支 workflow 相同）

1. **台北時間守衛**：台股需 ≥13:35、美股需 ≥05:10（台北），否則跳過
2. **抓報價** `scripts/fetch_us.py`（Yahoo Finance，stdlib）／`fetch_tw.py`
   （官方優先：指數定案＝證交所 FMTQIK 日統計 → MIS 快照 → Yahoo；個股收盤＝
   MIS → Yahoo；走勢／日線＝Yahoo。13:43 的 Yahoo `^TWII` 快照曾出現過時值
   （2026-11-11：44,029.53 vs 官方 44,257.15），故台股一律以官方來源 overlay
   並重推漲跌幅、修行走勢端點；任一官方來源失敗自動落到下一層）
   → 單行 JSON verdict：`ok=false`（來源異常）或 `report_exists=true`（假日／重跑，靜默結束）才繼續
3. **抓新聞** `scripts/fetch_news.py` — 免金鑰三層來源：
   Google News RSS（骨幹）→ Bing News RSS（異源備援）→ 媒體 RSS（LTN／CNBC／MarketWatch）
   去重、限 40 小時內、關鍵詞相關度排序，另依當日最大 movers 動態加一組查詢
4. **生成** `scripts/gen_report_cloud.py` — LLM（GLM，OpenAI-compatible 端點）只寫敘事 JSON
   （含 `open_items` 新追蹤項與 `resolutions` 對既有待查項的結論），Python 用
   `templates/report_base.html` ＋ `report_helpers.py` 確定性組裝 HTML
   （卡片／表格／走勢圖完全由數據決定，LLM 不碰數字）。生成前對系列記憶
   `data/state.jsonl` 做過期掃描並注入【系列記憶】摘要；生成後 Python 追加當日
   常規事實與收盤快報結論（`<market>-brief`），LLM 的 open／resolved 亦入帳
   （state 失敗只記 warning，不影響已寫出的報告）
5. **更新索引** `scripts/update_manifest.py` → commit（`docs(tw|us): add ... report <date>`）→ push → Pages 自動重建
6. **失敗告警**：任何步驟失敗自動開／留言 `automation-failure` 標籤的 Issue（GitHub 寄信通知）

## 系列脈絡

`CONTEXT.md` 是所有生成者的知識基底：市場位階、名家框架、台股階段防線、
寫作紀律（誠實條款：13:43 的台股報告禁止填入當日三大法人數據等）。重大事件後應人工更新此檔。

`data/state.jsonl` 則是自動維護的「系列記憶」（0.2.5 起；append-only JSONL，同 id 以最新
記錄為準），讓每次生成讀得到前幾日的脈絡——不只前一天。狀態與壽命：`routine`（Python
寫入的常規事實＋收盤快報結論，7 天）、`open`（待查，上限 21 天，逾期標 `expired` 並在
觀察清單註記追蹤逾時結案）、`resolved`（結論寫回而非刪除，7 天）、`expired`（3 天 grace
後清除）。prompt 注入按 `expires` 過濾並封頂 30 筆，正確性不依賴 prune 是否執行；實體
清除後歷史仍在 git。維運與未來 T86 晚間 run 用 CLI：
`python scripts/state_store.py show|add|resolve|prune`（`--file` 指定他檔供測試）；
`gen_report_cloud.py --dump-prompt PATH` 可不呼 LLM 檢視完整 prompt。

## 籌碼補完（tw-chips）

21:50（台北）的靜默 run：`fetch_chips.py` 抓證交所三大法人買賣金額（BFI82U）與融資融券
餘額（MI_MARGN）定案值，以 `routine` 記錄（topic `tw-t86`／`tw-margin`，附 `session_date`
防重）寫入 `data/state.jsonl` 後直接 commit——**不產報告頁、不呼 LLM**。隔日 13:43 的台股
報告經【系列記憶】讀到前一日籌碼，解讀與待查結案由該次生成完成（當日數據依然禁填，誠實
條款不變）。失敗照樣開 `automation-failure` Issue。端點有大小寫／新舊路徑陷阱（BFI82U
大寫走 rwd/、MI_MARGN 走舊式 exchangeReport/，其餘變體皆 404），改動前先讀
fetch_chips.py 頂部註記。同日重跑自動跳過（`duplicate: true`）；補抓舊日用
`--date YYYYMMDD`。若要外部主觸發，cron-job.org 加一條 21:50 的 `workflow_dispatch`
即可（GitHub schedule 已是備用）。

## 秘鑰與設定

| 項目 | 說明 |
|---|---|
| Secret `LLM_API_TOKEN` | 智譜 bigmodel.cn **coding plan** API key（`/api/coding/paas/v4` 端點專用） |
| Repo variable `LLM_MODEL`（可選） | 覆寫模型，預設 `glm-5.3-flash`（`thinking: disabled`，否則思考吃光輸出預算） |
| `GITHUB_TOKEN` | workflow 內建，contents:write ＋ issues:write，負責 commit/push/開 Issue |

**PAT 續期**：coding plan 的 API key 若到期／輪換，更新 secret 即可：
`gh secret set LLM_API_TOKEN -R ascetic168/market-brief`
（建議先用 `Get-Clipboard | gh secret set ... --stdin` 避免互動貼上截斷。）

## 除錯工具

- [smoke.yml](.github/workflows/smoke.yml)（手動觸發）：端點探測＋模型發現＋完整生成到 /tmp（不 push）
- workflow 失敗時先看該 run 的 log；生成步驟的錯誤訊息含 API 回應前 300 字預覽
- 本地重現生成：`LLM_API_TOKEN=... python scripts/gen_report_cloud.py us data/us_YYYYMMDD.json data/news_us_YYYYMMDD.json --out-dir /tmp/x`

## 已知限制

- Actions `schedule` 於尖峰可能延遲（官方文件明載）；報告時間以 commit 為準
- Yahoo 對資料中心 IP 偶發限流：fetch 腳本已內建重試；連續失敗會開 Issue 告警
- Google News RSS 偶發對 runner IP 拒答：有 Bing＋媒體 RSS 兩層備援，全失敗時報告以純數據模式產出

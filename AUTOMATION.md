# 自動化架構（AUTOMATION）

> 本 repo 的報告由 **GitHub Actions 雲端管線**全自動產出，不依賴任何本地機器。
> 本文件描述架構、排程、秘鑰與維運要點。

## 排程（GitHub Actions cron，UTC）

| Workflow | Cron (UTC) | 台北時間 | 涵蓋 |
|---|---|---|---|
| [tw-report.yml](.github/workflows/tw-report.yml) | `43 5 * * 1-5` | 週一至週五 13:43 | 台股 13:30 收盤＋13:33 定盤後 |
| [us-report.yml](.github/workflows/us-report.yml) | `33 21 * * 2-6` | 週二至週六 05:33 | 美股收盤（冬令台北 05:00／夏令 04:00 之後） |

GitHub 官方提醒尖峰時刻（整點）排程可能延遲數分鐘至更久，故刻意避開整點。
兩支 workflow 皆支援 `workflow_dispatch` 手動觸發，附：

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
4. **生成** `scripts/gen_report_cloud.py` — LLM（GLM，OpenAI-compatible 端點）只寫敘事 JSON，
   Python 用 `templates/report_base.html` ＋ `report_helpers.py` 確定性組裝 HTML
   （卡片／表格／走勢圖完全由數據決定，LLM 不碰數字）
5. **更新索引** `scripts/update_manifest.py` → commit（`docs(tw|us): add ... report <date>`）→ push → Pages 自動重建
6. **失敗告警**：任何步驟失敗自動開／留言 `automation-failure` 標籤的 Issue（GitHub 寄信通知）

## 系列脈絡

`CONTEXT.md` 是所有生成者的知識基底：市場位階、名家框架、台股階段防線、
寫作紀律（誠實條款：13:43 的台股報告禁止填入當日三大法人數據等）。重大事件後應人工更新此檔。

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

# Market Brief 每日市場快報

美股與台股盤後收盤報告，每個交易日自動產出並發布至 GitHub Pages。

> https://ascetic168.github.io/market-brief/

## 發布時間表（台北時間）

| 市場 | 產出時間 | 涵蓋交易日 |
|------|----------|-----------|
| 美股 | 週二至週六 05:33 | 前一個美股交易日（美東 16:00 收盤定案後） |
| 台股 | 週一至週五 13:43 | 當日台股（13:30 收盤、13:33 定盤後） |

報告由 **GitHub Actions 雲端管線**全自動產出與發布，不依賴任何本地機器：
抓報價 → 抓當日新聞（Google/Bing News RSS）→ LLM 撰寫敘事 → 組裝 HTML → commit → Pages 自動重建。
架構細節見 [AUTOMATION.md](AUTOMATION.md)。

## 報告內容

- **收盤快照**：指數與關鍵個股收盤價、漲跌幅、全日區間、成交量
- **全日走勢**：5 分鐘序列走勢圖（SVG）
- **收盤解讀**：量價結構與當日市場敘事的整合分析
- **觀察清單**：下一個交易日的關鍵檢驗點

## 資料來源

- [Yahoo Finance Chart API](https://query1.finance.yahoo.com/v8/finance/chart/) — 美股與台股報價、5 分鐘盤中序列
- [TWSE 臺灣證券交易所](https://www.twse.com.tw/) — 官方每日行情（FMTQIK）、三大法人買賣超（T86，盤後發布）
- 當日市場新聞 — 產出時網路檢索，來源標註於各報告「資料來源」章節

原始抓取資料保存於 [`data/`](data/)，報告位於 [`reports/`](reports/)，索引見 [`manifest.json`](manifest.json)。

## 免責聲明

本報告僅供資訊与研究目的，所有內容**不構成投資建議**。所引用之點位預測均為公開名家觀點之彙整；任何投資決策應自行判斷並承擔風險。

## 授權

報告內容與程式碼以 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)（內容）與 [MIT](LICENSE)（程式碼）授權。

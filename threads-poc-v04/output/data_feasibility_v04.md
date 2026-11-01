# Threads 品牌輿情研究 PoC v0.4 可行性報告

## 總結

- 授權狀態：`BLOCKED_AUTHORIZATION`
- 本次新搜尋：0 次。既有 20 筆資料僅作 legacy import，沒有冒充新資料。
- 去重後既有貼文：20 筆。
- 最近 12／24／7／30 天：依既有離線基準無法視為新取得樣本；可參考舊資料的發布時間，但不代表完整母體。
- 最新既有貼文：2026-10-30T20:23:50+08:00。

## 六項問題狀態

| 項目 | 狀態 | 證據 |
|---|---|---|
| P1 Excel 台灣時間 | PASS | Excel 使用真正日期值、`YYYY/MM/DD HH:mm`、固定標題列與篩選 |
| P2 情緒／議題人工複核 | PARTIAL | 20 筆全部 `review_status=pending`，保留複核原因，未標記 confirmed |
| P3 真實擷取時間 | FAIL（舊資料） | 舊資料 `actual_fetched_at_utc=NULL`；新搜尋未執行 |
| P4 最新搜尋／偏差 | NOT_TESTED | 原始碼確認有 cursor 邏輯，但沒有 Recent／日期區間 CLI；未做新網路測試 |
| P5 真實留言 | BLOCKED_AUTHORIZATION | replies 未執行，實際回覆紀錄 0，發布時間比例 N/A |
| P6 模型資料量 | PARTIAL | 有 20 筆可整理貼文，沒有足夠連續事件、回覆或歷史快照 |

## 工具能力

`ckelepel-threads` v0.1.1 的 `search` 有 cursor continuation 與 `--limit`，但 CLI 沒有 `start_date`、`end_date` 或已驗證 Recent 模式；程式最後依關鍵字符合與互動量排序，存在熱門內容偏差。`replies` 有 `--limit`，但本次未執行。

第二套工具 `threads-content-research-agent` 是 Go、Apache-2.0 的唯讀研究 CLI，README 說明支援公開搜尋、可見 replies、JSONL／SQLite 與 bounded research，但也明確說不是官方 API、不是完整搜尋引擎，搜尋可能為空且覆蓋不完整；需要 Go 1.26+。本次未建置、未搜尋、無法比較實測聯集或重複率。

## 模型可行性

### Model A：情緒／議題分類

目前只能作為人工標註資料整理起點。20 筆不足以評估類別平衡；規則分類不是 ground truth，且全部標為 pending。建議先取得 300–500 筆經人工確認的多日期貼文，再檢查商品、品質、價格、服務與爭議類別是否足夠。

### Model B：未來 6／12 小時升溫預測

目前不具備足夠條件。缺少多個獨立事件、事件前後完整觀測、可靠逐小時覆蓋、歷史互動 snapshots 與可避免資料洩漏的時間點資料。不能把既有 20 筆搜尋結果當成完整事件時間序列。

## 下一步

取得適用的研究／平台資料授權後，先以小量 Tier 1 關鍵字執行 Level 1，保存每次原始 response、request／response 時間與錯誤；再進行兩篇 replies、最多 10–20 則的驗證。只有在覆蓋率、日期分布、人工標註與事件數量足夠後，才評估 300–500 筆分類資料或約 10 個可比較事件。

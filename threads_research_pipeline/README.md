# Threads research data pipeline

離線處理 `quanlian.json` 的最小可用管線。原始檔案只讀，輸出放在
`threads_research_pipeline/data/processed/`。

## 使用

```bash
python3 threads_research_pipeline/src/pipeline.py \
  --input quanlian.json \
  --output-dir threads_research_pipeline/data/processed \
  --query 全聯 \
  --run-id quanlian-initial
```

輸出：`posts.csv`、`replies.csv`、`events.csv`、`collection_runs.csv`、
`threads_research.sqlite`、`quality_report.json`。

測試：

```bash
python3 -m unittest discover -s threads_research_pipeline/tests -v
```

## 目前資料語意

這個輸入是 `ckelepel-threads search --json` 的搜尋結果。它包含貼文及
擷取當下的互動累積值；`reply_count` 不等於已取得的回覆資料。沒有回覆
JSON 時，`replies` 會保持空表，不會由數量臆測留言。缺少的 parent ID、
發文當下互動數與事件標籤也會保留為 NULL。

## 工具檢查結論

已檢查本機 npx cache 的 `ckelepel-threads` v0.1.1 原始碼與 README：

- `search` 會先抓 HTML，再以 GraphQL cursor 分頁；單次執行受 `--limit`、
  `maxPages` 和服務端回應限制，沒有日期區間參數。
- 結果最後按是否符合關鍵字及 `like_count + reply_count` 排序，因此不能
  視為完整、隨機或按時間排序的事件樣本。
- `posts` 有 profile HTML 初始資料及 cursor 分頁，但同樣沒有日期區間。
- `replies` 會將初始頁及 cursor 頁轉為 reply records，輸出包含 id、
  `post_id`、`parent_id`、text、`created_at`；程式在無時間欄位時會使用
  當下時間作 fallback，這種值不可當成真實發佈時間，需在研究資料中標記。
- README 的「完整歷史」、「100% precision」等 benchmark/宣稱不是本地
  `quanlian.json` 的覆蓋率證據，不能直接用來支持論文結論。

本管線不執行新擷取、不使用 cookie/proxy，也不驗證平台授權或條款；正式
擴大收集前仍需完成研究倫理、資料保護與來源授權確認。

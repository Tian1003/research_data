# Threads PoC v0.5

延續 v0.4 的 Canonical Schema、record_id 與原始 payload；新增情緒對象、
人工複核歷史及明確的資料來源評估。最終 `output/` 只有三個檔案。

本輪使用者已確認尚無核准的公開搜尋權限或授權來源，所以沒有新的 Threads
搜尋／回覆請求。這不是即時蒐集成功，也沒有完成新增資料的模型驗證。
目前 20 筆均為 legacy；其真實擷取時間未知。

## 重建與驗證

Python 3.10+（本機 3.12）、Node.js 22；Python 程式僅用標準函式庫。
Excel builder 使用既有 runtime 的 `@oai/artifact-tool`，本機 node_modules
是指向 runtime 相依套件的 symlink，沒有修改既有 Node／Go 環境。

```bash
python3 threads-poc-v05/scripts/build_v05.py
node threads-poc-v05/scripts/build_xlsx.mjs
python3 threads-poc-v05/scripts/finalize_v05.py
python3 -m unittest discover -s threads-poc-v05/tests -v
```

基準時間是 config/run.json 內的本輪實際時刻。未來開始新輪次時才更換此值；
舊檔無法證明 actual_fetched_at，不因重新整理而填入新時間。

`finalize_v05.py` 直接解碼輸出 XLSX 的數值日期，逐列核對台灣 wall-clock，
並核對兩個指定時間範例、日期排序、native hyperlinks、autoFilter、下拉選單。
由 artifact-tool 產生的預覽與旁檔留在 internal/workbook，不放進 output。

## 人工標註：先編輯 Excel，再明確匯入

系統欄位在 A:P，人工欄位在 Q:V；W 是隱藏的 immutable record_id。
可排序／篩選整個表格，請勿刪除或編輯 record_id。人工分類和備註與系統提案
分開存放。未經人工確認維持 pending；confirmed/corrected 須四個人工欄位完整。

```bash
python3 threads-poc-v05/scripts/reviews.py \
  --workbook threads-poc-v05/output/threads_analysis_v05.xlsx \
  --data threads-poc-v05/output/threads_raw_v05.json \
  --state threads-poc-v05/internal/annotations.json \
  --reviewer 研究者代碼
```

再執行重建命令。匯入以 record_id＋原始 URL 核對，保留匯入者、時間、檔案
SHA256、修改前後值。若重建時 Excel 有尚未匯入的人工修改，程式會停止並
保留檔案。v0.4 若存在人工自由文字，也以其唯一 URL 對回 record_id 並保存。

## 可執行的官方 API 小測試

目前先跑預設 dry-run（不讀取 Token 值到報告、不連線）：

```bash
python3 threads-poc-v05/scripts/official_probe.py --mode search --keyword 全聯
```

結果記在 internal/official_probe_plan.json，具體列出尚缺核准與環境設定。
官方來源目前只驗證 TOP 的基本 keyword_search 請求形狀；未將未確認的
RECENT/date 參數寫入測試計畫。

待真正取得核准後，在 config/run.json 記錄非機密的：

- approved_api_permissions（如 threads_basic、threads_keyword_search）
- app_review_approved、research_use_approved
- approval_evidence_ref（核准資訊所在的本機檔案／來源）
- replies 額外需要 reply_access_approved_ids

Token 僅在自己的終端機／密鑰管理程式設定 THREADS_ACCESS_TOKEN，不放進
程式碼、對話或報告。手動將核准旗標改為 true 不能取代真實平台許可。

```bash
# 僅在真正取得適用核准與有效 Token 後執行；本輪沒有執行這些命令
python3 threads-poc-v05/scripts/official_probe.py --mode own --execute
python3 threads-poc-v05/scripts/official_probe.py --mode search --keyword 全聯 --execute
```

每次最多一個 GET、15 筆輸出目標；回覆每篇 10 筆。沒有自動分頁、Cookie、
代理、重試或付費服務呼叫。失敗／空資料會分別記錄；received_at 是本機收到
完整回應的時刻。新回應在 internal/official_responses，可用下列命令匯入：

```bash
python3 threads-poc-v05/scripts/build_v05.py --response 本機回應檔.json
```

不要把供應商文件中的合成示例、測試 fixture 或未核實的第三方資料匯入研究
樣本。來源評估與成本／申請步驟保存在 config/sources.json 及主要報告。

## 工具審查範圍

已下載兩個使用者指定 GitHub 專案的固定版本，放在 internal/source_review。
工具 A 的既有 npx 安裝可離線讀 CLI Help；最新下載副本缺 dependencies，
沒有額外安裝。工具 B 要求 Go 1.26+，本機 1.19，所以未建置或進行 live 測試。
原始碼審查不能證明有效分頁或資料覆蓋率。

# Threads 全聯資料量前置實驗

直接雙擊 **run_experiment.command**。它會完成本機檢查、兩批既有資料驗證、
SQLite 去重與快照保存，再更新 result_summary.md。預設為 offline，不會搜尋
Threads；也不建立排程。本專案不是 v0.6，沒有訓練模型或重建舊 Excel。

## 主要位置

- config/experiment.json：固定工具版本、關鍵字、數量、停止條件與授權範圍。
- config/relevance_review.json：可追溯的文字審查準則／特殊案例；並非人工真值。
- data/experiment.sqlite：records、sources、observations、query_runs、stage_results、relevance_history。
- data/analysis_latest.json：兩批驗證與模型資料品質統計。
- data/environment_latest.json：Terminal、Node、CLI Help、檔案雜湊與 GitHub 檢查。
- data/input_archive/：原始輸入的完整、依 SHA256 命名的封存副本。
- runs/experiment_*/：每次執行的獨立環境、計畫、分析與結果，不覆寫舊執行。
- result_summary.md：給研究者閱讀的最新摘要。

原有 v0.5、原始 JSON、second-batch JSON 與兩個時間檔都只讀。
匯入可重複執行：同一 source 不會重複新增觀測，兩批合併保持 37 個 ID、
40 筆觀測。派生相關性可以重評，修改前後保留於 relevance_history；manual_*
與 review_status、event_id 保留，不會被規則重寫。

## 計數定義

1. 唯一候選 ID：平台＋原始 ID 去重，尚不代表品牌有效。
2. 品牌候選：有效原始 Threads 貼文、可解析且不晚於基準的發布時間，以及
   direct／related 文字證據。direct、related 分列，context_only 不計入。
3. 真正新取得的品牌候選：本查詢品牌候選中，排除所有既有 ID，而非只排除
   先前的品牌有效集合。舊 ID 重新分類另列，不能當新增取得。
4. 人工確認：須由研究者確認；所有目前新審查維持 pending。規則及本次
   assistant 文字審查皆不是 ground truth。
5. 近期：按 taken_at 與該輪開始時刻計算；獨立提供 12h／24h／7d／30d，
   不把新 ID、近期發布與品牌相關混在一起。

第二批開始與結束相差 26 秒，只能證明提供了外層 CLI 的蒐集區間。
舊批次的精確收取時間未知，第二批也未記錄每個 HTTP 回應時間；因此保留
observed_at=NULL，另存 window_start/end。不能用此資料計算精確互動速度。

## 工具版本與界線

固定 ckelepel-threads Git SHA d4a18e5dfe65ab69ce4bcad167e54446ff9c9912，
package.json=0.1.1，但 src/index.js 匯出的 VERSION=0.1.0，兩者都記錄。
執行前比對五個核心檔案 SHA256；使用已有 npx cache，不做自動更新或安裝。

已核對的 CLI 參數只有 search、query、--limit、--no-expand、--json 等真實
選項。沒有添加 Recent／日期 CLI。工作器使用同一套 searchThreads SDK，
以 fetchFn 注入請求監督器，相當於逐一執行上述 CLI，方便記錄每次 HTTP。

上游 SDK 一組查詢會同時建立兩個 HTML facet、可能再 GraphQL 分頁、最多
重試兩次，並且有吞掉錯誤仍回 status=ok 的情況。因此不能直接用 CLI 次數
或 --limit 當網路上限。監督器會：

- 逐一執行／計數所有 HTTP，包含允許網域內的 redirect；不跟往其他主機。
- 禁用自動 topic expansion，使用已核對的 strict/limit 邏輯。
- 設定至少五秒 HTTP 間隔、單請求／單查詢 timeout 與回應位元組上限。
- 429、401、403、HTTP/GraphQL 錯誤、驗證要求、請求上限立即停止；重試時
  直接拒絕，不再向平台發請求。SDK 吞掉錯誤也會由監督器標為 FAILED。
- 不繼承 Cookie、代理、Token、帳號 session；不偽裝登入或瀏覽器身分。
- 每個 HTTP 保存原始 body、時間、狀態、SHA256；每個詞保存獨立 SDK JSON、
  stdout/stderr、Exit Code、query_result 與 manifest。
- 依實際 HTTP 內容中的 ID、文字和 metrics 對回收取時間；不同時刻快照另存，
  未找到確切匹配時不替該貼文補造單一收取時刻。

本輪只用既有真實貼文作為離線 mock 的解析素材；mock 回應沒有加入研究資料。
這些測試證明工作流程的邊界，不證明目前平台端搜尋或分頁可用。
工具可能以當下時間或 0 填補上游缺失值；來源 JSON 若未保留欄位存在性，
不能從輸出反推原始欄位完整。解析成功也不代表已獨立驗證真實發文時刻。

本輪環境檢查發現：直接 curl 可取得 GitHub 資訊，但 Codex 沙盒內 Python
子程序曾遇到 DNS 限制。已使用 Codex 正常 require_escalated 機制核准執行
入口，成功讀取同一 GitHub 專案。失敗與核准後成功的環境紀錄均保留在 runs。
這是本機執行／網路權限問題，不是 Threads 平台資料授權，也沒有關閉沙盒。
--approval-context 僅記錄執行脈絡，本身不會提供任何網路或資料授權。

## Stage A／B／C

A：四個核心關鍵字、每詞最多 20 筆輸出；總 HTTP 24、單詞 HTTP 6。
遇到錯誤／存取限制，或連續兩詞零新增品牌候選即停止。PASS 須完成當輪
查詢、結構／時間／最低相關性與至少一個真正新增品牌候選；不保證完整覆蓋。

B：A 真實測試 PASS、有至少 5 筆人工確認、研究者品質放行後，才可逐詞加入
延伸查詢。每詞 50、最多 6 詞／36 HTTP，前一詞結果不合格不進下一詞。
100／300／500 是要驗證的目標，不能按單詞邊際增益線性外推。本設定單輪
最多 300 個輸出，扣重後更少；不保證取得 500 篇。

Stage B 放行檔是本機 JSON，需 stage_a_execution_id、approved_by、
reviewed_at_utc，必須對應最新通過的 Stage A。人工 confirmed/corrected
標註必須有可靠的研究者確認紀錄，不能為了解除 gate 自動生成。

C：只規劃固定頻率（例如每小時）與快照保存。沒有安裝 cron／launchd、
登入項目或其他背景排程。未取得適用管道前不得啟用長期擷取。

背景詞另有獨立 context stage，取得他品牌或純背景不計入全聯候選；不會
自動加入 Stage A/B 補量。

## 授權後的啟用方式

目前 authorization.status=not_approved。要啟用本非官方 HTML/GraphQL
工具，必須先取得涵蓋該方法、品牌研究／保存／模型用途的適用許可，並將
真實核准證據路徑、approved_methods=["ckelepel-public-http"]、效期寫入設定。
單純修改旗標或取得官方 API Token，不能代替此工具方法的許可。

若核准的是官方 API／MCL／資料服務，就應使用相應 authorized adapter，
而不是將其許可套用到 ckelepel。具體申請入口在 result_summary.md。

具備許可後再把 default_mode 改為 live、default_stage 選 A，雙擊同一入口
即可依設定執行；目前雙擊只做離線工作並記錄授權 gate。B 不會因 A 結束
就自行啟動，C 永遠只輸出設計。

## 命令列（可選，不必每次手打）

```bash
python3 threads-collection-experiment/scripts/experiment.py run
python3 threads-collection-experiment/scripts/experiment.py plan --stage B
python3 threads-collection-experiment/scripts/experiment.py run --stage C
python3 -m unittest discover -s threads-collection-experiment/tests -v
node --test threads-collection-experiment/tests/transport.test.mjs
python3 threads-collection-experiment/scripts/verify_experiment.py
```

最後一個驗證命令只執行離線測試與原始檔完整性檢查，保存 data/verification_latest.json
及測試輸出，不會重新搜尋 Threads。

即使用 --live，沒有適用許可也不會啟動 Node 蒐集工作器。本機執行、GitHub
連線、來源使用授權是分別檢查的條件；網路環境錯誤不會歸類為平台授權錯誤。

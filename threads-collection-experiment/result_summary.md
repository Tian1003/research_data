# 全聯 Threads 蒐集前置實驗

本機 Terminal / Node / 讀寫已分別執行；GitHub 檢查：PASS。Codex 核准後執行；預設沙盒內子程序曾遇到 DNS 限制，失敗紀錄已保留。本輪 Threads HTTP 請求 0 次，未安裝排程。

```text
pwd: /Users/jiangtiancheng/research_data
node -v: v22.23.4
npm -v: 10.9.9
which npx: /Users/jiangtiancheng/.nvm/versions/node/v22.23.4/bin/npx
git --version: git version 2.38.0
```

固定工具與 CLI Help 校驗：PASS。

## 兩批既有真實紀錄

| 指標 | 數值 |
|---|---:|
| 第一批唯一 ID | 20 |
| 第二批唯一 ID | 20 |
| 交集 | 3 |
| 第二批新增 ID | 17 |
| 聯集候選 ID | 37 |
| 第二批品牌候選（直接＋間接） | 12 |
| 第二批新 ID 中的品牌候選 | 10 |
| 目前資料庫直接品牌候選 | 28 |
| 目前資料庫間接品牌候選 | 1 |
| 僅背景／地點 | 3 |
| 品牌相關性待判定 | 5 |
| 人工確認品牌貼文 | 0 |

品牌候選共 29 篇，是保守文字篩選的待人工研究樣本；不能將 37 個 ID 一律稱為品牌有效資料。標註維持 pending，未把程式審查冒充研究者確認。排除例：淡江大學冰箱抱怨、唱歌邀約與發飄帶集合地點；寶雅商圈／全聯關店另列間接相關。

第二批以其開始時間 2026-10-31T13:00:44+00:00（台灣時間 2026/10/31 21:00:44）為基準：

| 時窗 | 全部第二批貼文 | 品牌候選（直接＋間接） | 僅直接品牌候選 |
|---|---:|---:|---:|
| 12 小時 | 3 | 2 | 2 |
| 24 小時 | 8 | 5 | 4 |
| 7 天 | 9 | 6 | 5 |
| 30 天 | 13 | 6 | 5 |

第二批時窗為 2026-10-31T13:00:44+00:00 至 2026-10-31T13:01:10+00:00、26.0 秒。這是使用者提供的外層 CLI 起訖紀錄，非每篇 HTTP 精確收取時間；actual_fetched_at 仍不猜填，快照另外保留該區間。舊批次觀測時刻未知。taken_at 來自工具回傳；上游缺時間可能補當下，解析成功不等於已獨立查證發文時間。

## 自動化與三階段驗收

- Stage A：核心查詢最多 4 組，每組最多 20 筆；總 HTTP 上限 24，單查詢上限 6，序列執行、至少間隔 5 秒、無自動重試／擴詞；本機日期過濾不是原生 Recent 搜尋。遇到 401/403/429、登入／驗證、錯誤、預算耗盡或連續 2 查詢零新增品牌樣本即停止。計畫狀態：BLOCKED_AUTHORIZATION。
- Stage B：Stage A 實測通過、至少 5 筆人工確認與品質放行後，才加入延伸詞。每次查詢都先計算邊際增益與品質，最多 6 個詞各 50 筆。100／300／500 是探索目標；本設定單輪至多回傳 300 筆、且有重複，不能保證 500。計畫狀態：BLOCKED_AUTHORIZATION。
- Stage C：只保存每小時定期觀測設計，scheduler_installed=false；相同 record_id 不變，每次 metrics／HTTP 收取時間另存 observation。沒有 cron、launchd 或背景定時擷取。

每組詞的真正新增樣本為「本查詢唯一 ID 中，通過平台／原始貼文／品牌相關性／時間品質條件，且不在所有已取得 ID 中的集合」。舊 ID 重新分類另計，人工確認與待審再分列。不能把這次單一全聯查詢新增 17 個 ID／10 個品牌候選，外推成每個新關鍵字都能提供相同增益。

本輪執行狀態：BLOCKED_AUTHORIZATION；新的 Threads HTTP 請求 0 次。既有第二批是使用者已取得的資料，沒有冒充本輪自動搜尋。工具 package=0.1.1，但 src/index.js 導出的 VERSION=0.1.0；以固定 Git SHA＋核心檔案雜湊校驗。所有查詢獨立保存 JSON、stdout/stderr、起訖、Exit Code、HTTP journal 與回應；不繼承 Cookie、Token、Proxy。

## 模型可行性與權限

Model A：目前 29 篇待審品牌候選、人工確認 0 篇。議題 {'待判定': 6, '商品品質': 1, '價格與促銷': 6, '商品體驗': 14, '門市服務': 2}；暫定情緒 {'uncertain': 13, 'negative': 1, 'positive': 14, 'mixed': 1}，皆非 Ground Truth。可做標註試行，不能驗證 100／300／500 篇的取得能力或分類成效；熱門排序、廣告／圖文與多品牌情緒對象仍有偏差。

Model B：確認事件 0、真實回覆 0；品牌候選在 13143 小時跨度只有 28 小時有樣本，其餘是未觀測，不能補成全平台零聲量。共保存 40 筆觀測，其中 20 筆只有 CLI 蒐集區間；具兩個精確觀測時刻的貼文 0。欠缺連續時序、事件前後與正常時段對照，不能驗證未來 6／12 小時升溫。回溯模型不得使用事後累積互動；跨事件須按完整事件分組。

目前沒有已確認可直接使用的 Threads 公開資料管道：官方 App 的核准證據與環境 Token 未提供；MCL 顯示 Threads UI 可申請，但本地程式／原始匯出權限另需確認；資料服務 Key／契約及含全聯的公開授權資料包亦未提供。

具體下一步：

1. 在 [Meta App Dashboard](https://developers.facebook.com/apps/) 核對 Threads App、threads_keyword_search 公開搜尋正式核准與用途；先前自己的帳號存取不等於全站公開搜尋。官方 API 核准也不自動授權本非官方工具，應改接相應官方 adapter。
2. 與教授經 [Meta Research Tools Manager](https://www.facebook.com/research-tools-manager) 申請 MCL，確認碩士資格、Threads 歷史／回覆、匯出及模型用途。[SOMAR 官方範圍](https://www.icpsr.umich.edu/sites/somar/meta-content-library)目前把 Threads 列於 UI。
3. 或向 [LargitData](https://www.largitdata.com/社群媒體API/) 申請學術試用，先確認來源權利、模型與論文使用、保存規則及費用；其服務使用爬蟲，付費不自動等於平台授權。

拿到涵蓋方法的有效許可、Stage A 實測與人工品質驗收，才可進入中型實驗。執行程式、GitHub 可連線與合法資料取得是分開的條件。

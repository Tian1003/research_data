# Threads 全聯研究 PoC v0.5 可行性驗證

本輪真正新增 **0 篇全聯貼文、0 則回覆**；實際 Threads 搜尋 **0 次**。使用者已確認尚無正式核准的公開搜尋權限或授權資料來源。已查證替代管道與本機設定，但沒有可直接使用的已授權資料源；新蒐集與新增樣本的模型驗證仍未完成。

保留原有 20 篇唯一貼文、完整原始回應及 SHA256；沒有把 GitHub／文件下載、API dry-run 或測試用 fixture 計入研究樣本。v0.4 及先前原始檔保持不變。

## 六項問題與證據

| 項目 | 狀態 | 證據 |
|---|---|---|
| P1 | PASS | 重新讀取 XLSX，20 列台灣 wall-clock 數值、兩個指定例、降序、格式、篩選、超連結與下拉均通過 |
| P2 | PARTIAL | 已加情緒對象、反諷複核與有歷史的人工匯入；尚無人工真值標註 |
| P3 | PARTIAL | 已查核五種管道並提供有界官方 API 測試程式；目前沒有已核准可連線來源 |
| P4 | BLOCKED | 兩套固定版本原始碼已比較；尚未進行獲授權的新搜尋與有效分頁實測 |
| P5 | BLOCKED | 尚無適用的回覆存取授權；工具輸出的父節點／時間可能是推定值 |
| P6 | BLOCKED | 新增品牌樣本為零；缺少人工標註、確認事件與連續觀測 |

P1 的讀檔驗證包含：`2026-10-30T12:23:50Z → 2026/10/30 20:23`、`2025-10-02T10:00:29Z → 2025/10/02 18:00`；每列為數值日期，另檢查降序、格式、篩選、下拉選單、隱藏 ID 與原始網址超連結。v0.4 的底層確為 UTC `t=d` 值，因此上一版 P1=PASS 並不充分，本版已修正。

P2 保留系統與人工欄位，新增情緒對象、危機候選、複核優先級。蝦仁比較文把好市多的過敏負評與全聯商品分開；「最後一盒、不要去買」維持反諷待判定。20 篇須複核，優先級 {'medium': 15, 'high': 5}；人工完成 0 篇。初期預設 pending，程式不自行確認。Excel 的人工修改透過 `reviews.py` 明確匯入，以 record_id＋URL 核對並保存前後版本；重建遇到未匯入修改會停止。這是作業機制驗證，分類準確率仍未知。

## 新舊資料與時間覆蓋

統計基準固定為本輪實際時刻 **2026-10-31T20:19:14+08:00（Asia/Taipei）**，不是前版的午夜 replay。發布時間來自來源回傳，未逐篇向平台驗證；工具 A 本身可能補造缺失時間，此風險已記錄。

| 時窗 | 本輪新取得、且發布於時窗內 | 舊樣本按發布時間落入時窗 |
|---|---:|---:|
| 近 12 小時 | 0 | 0 |
| 近 24 小時 | 0 | 1 |
| 近 7 天 | 0 | 4 |
| 近 30 天 | 0 | 9 |

最新既有貼文：2026-10-30T20:23:50+08:00。0/20 篇具有可確認擷取時間；舊資料維持 NULL。保留 20 筆互動快照，其觀測時間未知，不能作歷史互動成長率。所有主網址為 Threads；Instagram CDN 僅是媒體網域。網址格式可解析不等於已逐篇測試可連線。

| 既有樣本熱度前五：發布時間 | 文字摘錄／原始來源 | 分數 |
|---|---|---:|
| 2025-10-02T18:00:29+08:00 | [一個最近廣為流傳的全聯小祕密 ​ ​ 全聯其實有免費wifi…](https://www.threads.com/@pxmart/post/DPTX9AUEfl_) | 22163 |
| 2025-05-01T23:31:52+08:00 | [在全聯被我抓到最後一盒 拜託大家不要去買…](https://www.threads.com/@c_bo1660909/post/DJHbdWzT7id) | 19129 |
| 2026-07-10T15:38:56+08:00 | [上次看到有人推這包 全聯的鮮凍白蝦仁 買回家試試真的很可以耶…](https://www.threads.com/@tainan_shaniu/post/DamrIMREapy) | 11252 |
| 2026-08-24T14:16:28+08:00 | [全聯的雞湯真的有人在買嗎？ 感覺冬天買來很不錯欸 不用備料…](https://www.threads.com/@yuyu70832/post/DcaZddnjy53) | 9617 |
| 2026-10-26T19:24:30+08:00 | [全聯這個酸菜白肉鍋真的超好吃 不小心加太多火鍋料 但是吃的好…](https://www.threads.com/@yunxi_cyc/post/De9Kyynk-pd) | 7455 |

熱度為 1×讚＋3×回覆＋4×轉發＋2×引用，僅作排序，缺任一指標則不可計算。較舊貼文有較長累積期；當前累積互動不可作為過去時間 t 的特徵。

## 可執行取得管道與下一步

| 管道 | 狀態 | 查證結果 | 可採取的下一步 |
|---|---|---|---|
| [Meta Threads API](https://www.postman.com/meta/threads/collection/dht3nzz/threads-api) | BLOCKED | 有官方搜尋端點；目前無公開搜尋核准／可用 Token | 先核對 App Review 與研究用途，核准後執行單次 GET |
| [Meta Content Library / SOMAR](https://www.icpsr.umich.edu/sites/somar/meta-content-library) | PARTIAL | 官方確認 Threads 在 UI；API 與原始資料匯出另查 | 與教授經 Research Tools Manager 申請並確認匯出條款 |
| [台灣青鳥運動 Threads 論文資料](https://arxiv.org/html/2602.02640v1) | BLOCKED | 62,321 篇台灣 Threads 的研究先例；作者不能直接分享原始資料 | 參考其研究管道，不把論文授權當資料授權 |
| [FediverseSharing 研究資料候選](https://arxiv.org/html/2502.17926v1) | NOT_TESTED | opt-in 聯邦樣本；未找到含全聯的明確授權資料包 | 先確認發布位置、授權、Threads ID 與品牌覆蓋 |
| [LargitData / InfoMiner 社群媒體 API](https://www.largitdata.com/社群媒體API/) | PARTIAL | 官網提供搜尋／回覆示意及申請試用；來源為爬蟲 | 申請學術樣本與書面用途條件；USD 依範圍報價 |

官方 API：本機只找到先前的 starter 程式，沒有核准證據，環境亦未設定 THREADS_ACCESS_TOKEN。過去曾成功取得自己的資料屬使用者歷史回報，沒有在本輪重驗。Token 含 scope、測試帳號可用、App 正式公開搜尋核准是不同事情。Meta 文件頁本次回傳 429，已停下；不把未驗證的 RECENT／日期參數當成官方 API 能力。

MCL：SOMAR 當前官方頁明列 Threads 在 **UI**，不能從這點推論 Threads API／原始全文自由匯出也已開放。可透過 [Meta Research Tools Manager](https://www.facebook.com/research-tools-manager) 由研究者與教授申請，準備機構信箱、研究目的及資料保護安排，並確認碩士身分資格、日期／帳號覆蓋、回覆、匯出與機器學習條款。原始資料存取、在安全環境分析、可匯出統計是不同許可，核准前不保證能放進本機 Excel。

公開資料集：青鳥研究是具體的台灣 Threads 研究先例，但作者明說受分享限制，論文 CC BY 不等於原始貼文資料可重用。FediverseSharing 是 opt-in 聯邦樣本，未找到本輪可驗證且包含全聯的授權資料包。故沒有把不相關或無明確授權的資料加入樣本。

LargitData：官網有學術用途說明、Threads 搜尋／回覆與日期參數示意，USD 按範圍報價，試用需申請；同頁明說資料來自爬蟲。需請廠商提供用途、來源權利、保存／刪除與模型使用的書面條件。尚未有 Key／契約，不能將付費或官網示意資料視為已獲平台資料授權。未替使用者填表、付款或對外聯繫。

準備好的 `official_probe.py` 預設只產生計畫。本輪 dry-run 明確列出缺少的核准與憑證，不發請求。未來有適用核准後，可對自己的 /me/threads 或核准的 keyword_search 做 **單次 GET、15 筆輸出目標、零自動重試／分頁**；回覆每次 10 筆，須另有該貼文回覆存取權。收回應時刻記作觀測時間，錯誤／空結果／429 分別保留，不虛報成功。Token 僅由本機環境讀取，不寫入程式碼或報告。

## 工具比較（固定原始碼版本；非 live 實測）

| 比較項目 | 工具 A：ckelepel-threads | 工具 B：threads-content-research-agent |
|---|---|---|
| 新搜尋請求／新原始結果／新唯一貼文 | 0 / 0 / 0，受授權限制 | 0 / 0 / 0，受授權與 Go 版本限制 |
| Recent／原生日期區間 | 無 CLI；HTML recent facet 未驗證且結果被重新排序 | cli/search.go:23–24 拒絕非 top；未提供日期區間 |
| 分頁與 --limit | Map 去重，maxPages、cursor、limit 控制收集與最終 slice；多 facet／單頁可能先取超額資料 | 先取得 SSR＋至多 20 GraphQL 頁，再於 Search 迭代輸出套 limit；小 limit 不限制底層至同樣小請求量 |
| 回覆時間／父節點 | created_at 缺 taken_at 時補 Date.now；parent_id 依 thread_items 順序推定 | Timestamp 有欄位；PostReplies 將 ParentID 與 RootID 都設為 root，不能確認巢狀父節點 |
| 回覆數量限制 | 最後 slice(0,limit)，初始 HTML／整頁可能超額；非服務端嚴格傳輸上限 | 輸出 limit；初始 HTML 和 GraphQL 單視窗仍可能較大 |
| 最近 24h／7d／30d 新樣本、有效分頁、網址有效率、交集／獨有 | NOT_TESTED；無新搜尋，非零覆蓋率結論 | NOT_TESTED；無新搜尋，無法比較是否更好 |

兩者原始碼確有去重與有界 continuation，但有效分頁、近期覆蓋率、交集／獨有貼文均尚未實測。工具 A 可能吞掉網路錯誤而仍回 status=ok；其無關結果 fallback 也可能在 strict 無命中時輸出候選結果。因此 status=ok、limit、開源授權均不能獨立證明資料完整或研究使用權。

## 回覆與模型判斷

P5：貼文顯示 reply_count 合計 **2074**；實際回覆紀錄 **0**。文字、時間、父節點可確認率皆 **N/A（分母為 0）**。尚未驗證兩篇 live 回覆；既有輸出中 parent/time 的工具推定不當成平台證據。本版 adapter 對無法確認的值保留 NULL。

Model A：**PARTIAL，只可開始人工標註**。20 篇涵蓋 18 個發布日期；字數 min/median/max=13/40.5/124，19 篇有媒體，1 篇需多品牌情緒對象判讀。暫定情緒 {'uncertain': 7, 'positive': 11, 'mixed': 1, 'negative': 1}；議題 {'門市服務': 1, '待判定': 3, '商品體驗': 10, '價格與促銷': 5, '商品品質': 1}。人工標註完成率 0/20，沒有可作 Ground Truth 的新資料；300–500 篇只是探索目標，仍須檢查類別平衡與跨日期分布。

Model B：**BLOCKED，目前不能驗證 6／12 小時升溫預測**。確認獨立事件 0 個，沒有事件前後 3–7 天的完整觀測，也沒有已知時間的多次互動快照。發布時間跨度 13126 小時僅 19 小時有樣本，其餘 13107 小時應視為未觀測而非零聲量。JSON 內小時聚合僅供管線示範，不代表全平台聲量。主要障礙是授權／覆蓋率、時間連續性與事件不足，不僅是總筆數；跨事件驗證應按完整事件分組，時間 t 僅用 t 前已可得資訊。

## 查證來源

- [Meta Threads API](https://www.postman.com/meta/threads/collection/dht3nzz/threads-api)
- [Meta Content Library / SOMAR](https://www.icpsr.umich.edu/sites/somar/meta-content-library)
- [台灣青鳥運動 Threads 論文資料](https://arxiv.org/html/2602.02640v1)
- [FediverseSharing 研究資料候選](https://arxiv.org/html/2502.17926v1)
- [LargitData / InfoMiner 社群媒體 API](https://www.largitdata.com/社群媒體API/)
- [ckelepel-threads](https://github.com/wongedyan/ckelepel-threads/tree/d4a18e5dfe65ab69ce4bcad167e54446ff9c9912)
- [threads-content-research-agent](https://github.com/Egor01KKK/threads-content-research-agent/tree/981cccd2eb53d44f46cc5675b2388c8c7a6ad758)

來源均於 2026-10-31 查證；原始碼 SHA、完整管道條件、錯誤與統計保留於 JSON。兩張 Excel 工作表與本報告共用同一份統計，檢查紀錄留在 internal，不額外交付重複 CSV。

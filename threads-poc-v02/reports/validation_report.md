# Threads 全聯輿情資料蒐集 PoC v0.2 驗證報告

- 測試型態：離線 replay；網路請求：0 次
- run_started_at：2026-10-31T00:00:00+08:00（Asia/Taipei）
- 搜尋視窗：2026-10-30T12:00:00+08:00 至 2026-10-31T00:00:00+08:00
- recent_search_verified：`false`
- 原始結果：20 筆；唯一 ID：20 筆
- 12 小時內且 direct_brand／brand_related：2 筆；目標 20 筆：`未達成`
- 最新合格貼文：2026-10-30T20:23:50+08:00；距 run start：3.6028 小時

## 搜尋與來源限制

本次沒有新搜尋，因此無法報告 Tier 1／Tier 2 各自的網路取得筆數。既有 JSON 的 query 是「全聯」，本報告只對其做本機時間與相關性過濾。工具原始碼有 cursor 分頁與 replies limit，但 CLI 沒有 start_date／end_date 或已驗證 Recent 排序；結果也會依互動量排序，因此 `recent_search_verified=false`。

## Table A：最新貼文 Top 20

| post_id | published_at_tw | age_hours | like_count | reply_count | heat_score | post_url |
|---|---|---|---|---|---|---|
| 4019341725345268536 | 2026-10-30T20:23:50+08:00 | 3.6028 | 48 | 19 | 105 | https://www.threads.com/@ohoh__qqq/post/DfHkgD6HEM4 |
| 4019332618646715688 | 2026-10-30T20:03:27+08:00 | 3.9425 | 11 | 4 | 23 | https://www.threads.com/@3amqooo/post/DfHibiok_0o |

## Table B：熱度貼文 Top 20

| post_id | published_at_tw | age_hours | like_count | reply_count | heat_score | post_url |
|---|---|---|---|---|---|---|
| 4019341725345268536 | 2026-10-30T20:23:50+08:00 | 3.6028 | 48 | 19 | 105 | https://www.threads.com/@ohoh__qqq/post/DfHkgD6HEM4 |
| 4019332618646715688 | 2026-10-30T20:03:27+08:00 | 3.9425 | 11 | 4 | 23 | https://www.threads.com/@3amqooo/post/DfHibiok_0o |

## 熱度公式

`heat_score = likes * 1 + replies * 3 + reposts * 4 + quotes * 2`。這是本次排序用啟發式分數，不是正式模型權重；互動值是擷取時快照。

## 來源與媒體網域

- post_url_host：{'www.threads.com': 20}
- media_hosts：{'instagram.ftpe7-2.fna.fbcdn.net': 7, 'instagram.ftpe7-4.fna.fbcdn.net': 11, 'instagram.ftpe7-1.fna.fbcdn.net': 5, 'instagram.ftpe7-3.fna.fbcdn.net': 5}
- 媒體 URL 若出現 Instagram CDN，只代表檔案儲存網域；主平台仍依貼文 URL 判定為 Threads，不應誤分類為 Instagram。

## 缺漏與研究限制

- 本次只留下既有搜尋結果中符合時間窗與品牌文字的資料，不能宣稱是 Threads 最近 12 小時完整貼文。
- 不足 20 筆時沒有用舊貼文、其他品牌或背景詞補足。
- `reply_count` 不是回覆全文；本次沒有執行 replies。
- 互動數不是發文當下數值；沒有多次快照就不能計算真正互動成長率。
- 逐小時統計只能描述觀測樣本，不能代表全平台聲量。

## 結論

本次離線資料在設定的 12 小時窗內只有 2 筆合格全聯貼文，不能證實工具具備真正 Recent 排序或完整覆蓋。可支援資料管線與小時聚合示範，但尚不足以支撐事件級 6／12 小時預測研究。正式網路測試前仍需確認研究倫理、Meta／Threads 授權與資料保存規則。
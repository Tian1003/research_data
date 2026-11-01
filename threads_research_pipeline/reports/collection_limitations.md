# 蒐集能力與限制（離線原始碼審查）

## 已確認

- `search <query>` 支援 `--limit`、`--no-strict`、`--no-expand`、`--json`、`--csv`、`--dataset`、`--db`。
- `replies <url_or_code>` 支援 `--limit`、`--no-tree`、`--json`、`--csv`。
- `search` 的原始碼會先解析初始 HTML，之後若有 cursor 與 `has_next_page`，以 GraphQL cursor 分頁；搜尋結果最後由工具依「是否符合關鍵字」及 `like_count + reply_count` 降序排序。這不是明確的 Recent 排序。
- `--limit` 同時影響搜尋收集迴圈與最後輸出切片；因此是本次執行的上限，不是平台總量或覆蓋率保證。
- 原始碼未提供 `start_date`、`end_date` 或 `recent` CLI 參數。程式內 GraphQL variables 有 `recent: 0`，不能解讀成使用者可設定的時間範圍搜尋。
- `replies` 的 `--limit` 會限制回覆結果；輸出欄位含 reply ID、`post_id`、`parent_id`、text、`created_at`。但其 `created_at` 在來源缺少 `taken_at` 時會 fallback 到擷取當下時間，必須在研究資料中辨識。

## 尚未驗證

本次未向 Threads 發出新的搜尋或 replies 請求，因此沒有聲稱回覆端點在目前環境必然可用、完整或不遺漏。README 的 benchmark 與「完整歷史」宣稱不等於本研究樣本的覆蓋率證據。

## 條款與授權

工具採 MIT 開源授權只代表程式碼授權，不代表 Meta/Threads 內容的自動擷取、保存、再利用或論文發布已獲授權。Threads 條款的「How You Can’t Use」文字對 robot、spider、crawler、scraper 或其他自動／手動收集資料有明確限制；正式研究應先向指導教授、研究倫理審查與 Meta／官方資料方案確認。這也是本次不執行網路測試的原因。

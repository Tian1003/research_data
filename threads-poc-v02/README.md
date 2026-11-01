# Threads 全聯輿情資料蒐集 PoC v0.2

本資料夾是以既有 `quanlian.json` 進行的離線 replay。因尚未確認研究用
自動蒐集授權，本次沒有對 Threads 發出新請求，也沒有使用 Cookie、Proxy
或大量擷取。

執行：

```bash
python3 threads-poc-v02/scripts/build_poc.py \
  --input quanlian.json \
  --run-started-at 2026-10-31T00:00:00+08:00
```

測試：

```bash
python3 -m unittest discover -s threads-poc-v02/tests -v
```

`data/raw/` 只保存輸入檔案的 provenance，不複製或覆寫工作區原始
`quanlian.json`。輸出資料將標記為離線分析，不能解讀成 Threads 最近 12
小時的完整母體資料。

# Threads 輿情資料分析整理與近期資料取得驗證（PoC v0.3）

本版本以工作區既有 `quanlian.json` 進行離線整理。因尚未確認研究用自動
蒐集授權，本次沒有新的 Threads 網路請求，`actual_fetched_at` 保持 NULL。

執行：

```bash
python3 threads-poc-v03/scripts/build_v03.py \
  --input quanlian.json \
  --run-started-at 2026-10-31T00:00:00+08:00
```

測試：

```bash
python3 -m unittest discover -s threads-poc-v03/tests -v
```

`threads_analysis.csv` 是主要閱讀表；`posts_normalized.jsonl` 與
`data_provenance.csv` 保存研究所需的完整欄位與來源追溯。舊版
`threads-poc-v02` 不會被覆寫。

# Threads 品牌輿情研究 PoC v0.4

本版保留舊資料，並建立 Canonical Schema v0.4。因尚未取得涵蓋本次
自動蒐集的研究授權，網路搜尋與 replies 測試標為
`BLOCKED_AUTHORIZATION`，不把既有 20 筆資料冒充新資料。

執行離線整合：

```bash
python3 threads-poc-v04/scripts/build_v04.py --input quanlian.json
node threads-poc-v04/scripts/build_xlsx.mjs
python3 -m unittest discover -s threads-poc-v04/tests -v
```

最終交付只放在 `output/`：原始／整合 JSON、兩工作表 Excel、可行性報告。

# 使用說明

這個專案有兩個入口，解決不同的場景。

---

## batch.py — 整個頻道批次處理

**解決的問題**：YouTube 頻道累積了大量影片，每支手動寫標題和說明既耗時又品質不一。

**做什麼**：
1. 透過 YouTube Data API 抓取指定頻道在 `SINCE` 日期之後的所有影片（自動區分一般影片與 Shorts）
2. 逐支透過 NotebookLM 分析內容，再由 Gemini 生成符合 B2B 規範的標題與說明
3. 每處理完一支就寫入 `results.json`，中斷後重跑會自動略過已完成的影片
4. 全部跑完後自動開啟瀏覽器顯示 `results.html` 結果總覽

**執行**：
```bash
python batch.py
```

**需要的環境變數**（`.env`）：
```
YOUTUBE_API_KEY=...
GEMINI_API_KEY=...
GEMINI_MODEL=...
channel=@頻道handle
SINCE=2026-03-21
```

**前置設定**（只需做一次）：
```bash
pip install -r requirements.txt
playwright install chromium
notebooklm login
```

**注意**：每支影片需要約 2–5 分鐘（NotebookLM 索引時間為主），頻道影片多時需長時間執行。

---

## app.py — 單支 MP4 上傳分析

**解決的問題**：影片還沒上傳到 YouTube（或根本不在 YouTube 上），無法用 batch.py 處理，但仍需要快速生成標題、說明、字幕、縮圖。

**做什麼**：啟動一個本地網頁，讓你上傳 MP4 後自動產出：
- **標題**（50 字以內，B2B 直述式）
- **說明**（含章節時間戳、hashtag）
- **字幕**（選用：SRT 格式，可下載）
- **縮圖**（選用：Imagen 3 生成，16:9）

**執行**：
```bash
python app.py
```

瀏覽器會自動開啟 `http://localhost:5000`。

**需要的環境變數**（`.env`）：
```
GEMINI_API_KEY=...
GEMINI_MODEL=...
```

**前置設定**（只需做一次）：
```bash
pip install -r requirements.txt
```

**上傳大小**：
- 500 MB 以下：讀入記憶體處理
- 500 MB 以上：串流寫入磁碟

**分析流程**（頁面上可即時追蹤進度）：
1. 上傳影片至 Gemini
2. Gemini 處理影片中
3. 分析影片內容
4. 提取章節時間戳
5. 生成標題與說明

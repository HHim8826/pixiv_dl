<h1 align="center">- pixiv異步爬蟲 -</h1>
<p align="center">
<img src="https://raw.githubusercontent.com/HHim8826/pixiv_dl/main/img/c1.png" width="750">
</p>
<p align="center">
<img src="https://img.shields.io/badge/version-V3.0.0-green.svg?longCache=true&style=for-the-badge">
<img src="https://img.shields.io/badge/python-3.9%2B-blue.svg?longCache=true&style=for-the-badge">
<img src="https://img.shields.io/badge/license-MIT-blue.svg?longCache=true&style=for-the-badge">
</p>

## 安裝

### 編譯版本（Windows，免安裝 Python）

從 [Release 頁面](https://github.com/HHim8826/pixiv_dl/releases) 下載
`pixiv-dl-vX.Y.Z-windows-x64.zip` 並解壓，把 `config.example.toml` 複製成
`config.toml` 填入 cookie 後執行 `pixiv-dl.exe` 即可。

exe 由 GitHub Actions 在合併進 `main` 時自動建置與發佈，版本號取自套件本身。

### 源碼版本

需要 Python 3.9 或更高版本。

```
git clone https://github.com/HHim8826/pixiv_dl.git
cd pixiv_dl
pip install -e .
```

## 設定

複製範例設定檔並填入自己的 cookie：

```
cp config.example.toml config.toml
```

`config.toml` 已被 `.gitignore` 忽略，**不會**被提交進 git。也可以改用環境變數，優先權高於設定檔：

```
# PowerShell
$env:PIXIV_COOKIE = "..."

# bash / zsh
export PIXIV_COOKIE="..."
```

### 獲取 Cookie

1. 打開瀏覽器並登入 [Pixiv](https://www.pixiv.net/)
2. 於首頁按 `F12` 打開開發者工具，切到「網路」分頁
3. 按 `F5` 重新整理，點擊第一筆紀錄，複製請求標頭中的 `cookie` 值
4. 貼進 `config.toml` 的 `[login].cookie`

## 使用

不帶參數會進入互動式選單（與舊版相同）：

```
pixiv-dl
```

也可以直接用子命令，方便寫進腳本或排程：

```
pixiv-dl id 92462879
pixiv-dl search "初音ミク" --mode safe
pixiv-dl ranking --mode daily --pages 3 --only-illust
pixiv-dl user 12345
pixiv-dl premium "初音ミク" --order female --pages 2
pixiv-dl popular "初音ミク" --min-bookmarks 5000
pixiv-dl search "初音ミク" --hide-ai
```

共用選項：

| 選項 | 說明 |
| --- | --- |
| `--out-dir PATH` | 輸出目錄（預設 `img/`） |
| `--concurrency N` | 同時請求數上限（預設 4） |
| `--config PATH` | 指定設定檔 |
| `--no-progress` | 不顯示進度條 |
| `-v, --verbose` | 輸出除錯訊息 |

安裝後也可以用模組形式呼叫：

```
python -m pixiv_dl ranking --pages 1
```

本專案採 src layout，未安裝時 `src/` 不在 `sys.path` 上，要直接從原始碼跑得自己指定：

```
PYTHONPATH=src python -m pixiv_dl ranking --pages 1
```

離開碼：`0` 全部成功、`1` 有作品下載失敗、`2` 設定錯誤、`130` 使用者中斷。

## 圖片存放結構

預設依「來源」分類，多頁作品另開子資料夾：

```
img/
├── ranking/
│   └── daily-2026-08-23/
│       ├── 111/               ← 多頁作品自成一夾
│       │   ├── 111_p0.png
│       │   ├── 111_p1.png
│       │   └── 111_p2.png
│       └── 222_p0.png         ← 單張直接平鋪
├── search/
│   └── miku/
├── popular/
│   └── miku-5000/
└── user/
    └── 54321/
```

排行榜的資料夾名帶日期，否則每天的排行會互相覆蓋。

在 `config.toml` 用 `path-template` 自訂，可用欄位 `{kind}` `{label}` `{date}`：

```toml
[download]
path-template = "{date}/{kind}/{label}"   # img/2026-08-23/search/miku/
multipage-dirs = "auto"                   # auto / always / never
```

指令列可個別覆蓋：

```
pixiv-dl search miku --path-template "{kind}"
pixiv-dl search miku --flat        # 全部平鋪，等同 v3.0 的行為
```

搜尋詞會變成資料夾名，所以路徑片段一律經過清理：分隔符與 Windows 不合法字元換成 `_`、
保留名稱（`CON` / `NUL` / `COM1`…）加上底線前綴、結尾的點與空白去掉、過長截斷。
`--flat` 之外的任何輸入都不可能跳出輸出目錄。

### 從 v3.0 升級

舊版把所有檔案平鋪在 `img/`。啟用新結構後，舊檔案不會被自動搬移，
重跑同樣的指令會下載到新的子目錄。想維持原樣就設 `path-template = ""` 或加 `--flat`。

## 過濾 AI 生成作品

搜尋類指令（`search` / `premium` / `popular`）會送出 Pixiv 的 `ai_type` 參數：

| 參數 | 行為 |
| --- | --- |
| `ai_type=1` | 隱藏 AI 生成作品 |
| `ai_type=0` | 顯示（預設） |

```
pixiv-dl search "初音ミク" --hide-ai     # 送 ai_type=1
pixiv-dl search "初音ミク" --show-ai     # 送 ai_type=0
```

想把「隱藏」設成預設值，在 `config.toml` 加上：

```toml
[search]
hide-ai = true
```

指令列旗標的優先權高於設定檔，`--hide-ai` 與 `--show-ai` 互斥。互動模式每次都會詢問，
預設值取自設定檔。

排行榜（`ranking`）與使用者作品（`user`）**不支援**這個參數，Pixiv 端點不吃，
所以那兩條路徑不會送出 `ai_type`。

## 關於 `popular`（免 premium 的熱門搜尋）

Pixiv 的搜尋預設排序是 `date_d`（**最新優先**），非 premium 帳號無法改成人氣排序。
所以「抓前 N 頁再逐件查收藏數」其實是在檢查「最新的 N×60 件作品」——
剛投稿的作品還沒累積收藏，這條路幾乎必然回傳空清單，而且要花掉幾千次請求。

因此 `popular` 改為優先利用 Pixiv 自動掛上的 `<N>users入り` 標籤，讓伺服器端先篩：

| `--min-bookmarks` | 實際搜尋詞 | 是否需要逐件驗證 |
| --- | --- | --- |
| 5000 | `初音ミク 5000users入り` | 否——命中標籤即為證明 |
| 3000 | `初音ミク 1000users入り` | 是，但候選數已大幅縮小 |
| 50 | `初音ミク`（無標籤可用） | 是，逐件查詢 |

門檻剛好等於標籤門檻（100 / 500 / 1000 / 5000 / 10000 / 20000 / 30000 / 50000 / 100000）時最快，
因為收藏數只增不減，命中標籤本身就保證 `>=` 門檻。

若標籤搜不到結果會自動退回逐件查詢，並在 log 中說明。想強制走舊路徑用 `--no-users-tag`。
逐件查詢階段有進度條與預估時間，不會再讓你對著空畫面等。

## 被 Cloudflare 擋下時

Pixiv 位於 Cloudflare 後方。請求太快時回傳的不是 Pixiv 的限流訊息，而是
Cloudflare 的挑戰頁，log 會顯示 `Cloudflare 機器人挑戰頁`。

連續被擋 5 次（`challenge-limit`）程式會主動中止，因為繼續重試只會加深機器人嫌疑。
處理方式，依效果排序：

1. **調大 `request-interval`**（`config.toml` 的 `[download]`）——這是真正決定每秒速率的旋鈕，
   比 `concurrency` 重要得多
2. **調小 `concurrency`**
3. **等幾分鐘再跑**——已下載的檔案會自動跳過，直接重跑同一個指令即可續傳

實測參考值（本地模擬每秒 8 次請求即觸發挑戰，共 60 件作品）：

| 設定 | 成功 | 失敗 | 觸發挑戰 | 耗時 |
| --- | --- | --- | --- | --- |
| `concurrency=8, interval=0` | 12/60 | 48 | 216 | 10s |
| `concurrency=4, interval=0.35`（預設） | 60/60 | 0 | 0 | 43s |
| `concurrency=2, interval=1.0`（保守） | 60/60 | 0 | 0 | 120s |

慢，但會拿到全部檔案。

## 開發

```
pip install -e ".[dev]"
pytest -q
ruff check .
ruff format .
```

## 從 v2 升級

- 進入點由 `python pixiv_img_async.py` 改為 `pixiv-dl` 或 `python -m pixiv_dl`
- 設定從 `pyproject.toml` 搬到 `config.toml`（**請把舊的 cookie 從 `pyproject.toml` 移除**）
- 已下載過的檔案會自動跳過，可以安全地重跑同一個指令

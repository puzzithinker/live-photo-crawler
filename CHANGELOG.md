# Changelog

記錄初始版本發布後的錯誤修復與健壯性改善。

---

## [0.2.0] — Post-Release Robustness Overhaul

### CLI 重構

- **argparse 取代互動式輸入**：`main.py` 從原本的 `input()` 提示改為 `argparse` 命令行介面
  - 位置引數：直接傳入一個或多個 URL（`python main.py url1 url2`）
  - `-o/--output`：指定儲存路徑（預設 `./res`）
  - `-f/--file`：從檔案讀取 URL 列表（每行一個，支援 `#` 註解）
  - 無引數時自動降級為互動模式（向後相容）
- **批次處理**：支援同時處理多個 URL，每個 URL 間以分隔線區隔
- **URL 檔案讀取**：`read_urls_from_file()` 支援 UTF-8 編碼、空白行跳過、`#` 開頭註解行

### 錯誤修復

- **Code 9 版本過期崩潰**（`TypeError: 'NoneType' object is not subscriptable`）
  - **根因**：API 回傳 `{"Code": 9, "Msg": "有新版本需要刷新页面", "Data": null}`，硬編碼 `cv=135` 已過期（SPA 升級至 v2.1.37，需要 `cv=137`），程式直接存取 `null` 的 `Data["Entity"]` 導致崩潰
  - **修復 1**：新增 `ApiError` 異常類別，`_api_call()` 統一處理 API 錯誤回應，不再直接存取可能為 `null` 的 `Data`
  - **修復 2**：新增 `_fetch_cv()` 函數，動態從 SPA HTML 提取版本號（`2.1.37` → `cv=137`）
  - **修復 3**：Code 9 自動失效 `cv`/`appKey` 快取並重新提取，重試最多 3 次
- **cv 提取正則表達式錯誤**：初始版本只捕獲 patch 部分（`37`）而非 `minor+patch`（`137`），已修正為 `match.group(3) + match.group(4)`
- **photoplus URL 解析錯誤**：原使用 `parts[3]` 取 ID，改為 `parts[-1]` 避免路徑深度不同時索引錯誤

### 動態配置

- **動態 appKey 提取**：新增 `_fetch_spa_version()` 和 `_fetch_app_key()`
  1. 從 `https://live.pailixiang.com/` HTML 提取 JS bundle URL
  2. 從 JS bundle 中以正則提取 `appKey`（`appKey:"([0-9a-f]{30,})"`）
  3. 提取失敗時降級使用 `FALLBACK_APP_KEY`
- **動態 cv 提取**：版本號從 SPA HTML 解析（如 `2.1.37` → `cv=137`），不再硬編碼
- **快取機制**：`_CACHED_CV` 和 `_CACHED_APP_KEY` 模組級變數，避免每次 API 呼叫都重新提取
- **Code 9 自動重設**：API 回應 `Code: 9` 時，自動將快取設為 `None`，觸發重新提取

### 網路韌性

- **API 重試邏輯**：`_api_call()` 最多重試 3 次，每次重新生成 `ak`
- **指數退避**：`ConnectionError` 和 `Timeout` 使用 2ⁿ 秒退避（2s, 4s）
- **請求超時**：API 呼叫 30 秒、圖片下載 60 秒
- **單照片下載失敗隔離**：`_download_image()` 重試 3 次後回傳 `False`，不中斷整批下載；失敗檔案名稱在最後列出
- **`SiteChangeError`**：當 SPA HTML 結構改變（找不到 JS bundle URL 或 appKey），拋出描述性錯誤而非靜默失敗

### 新增常數

| 常數 | 值 | 用途 |
|---|---|---|
| `FALLBACK_APP_KEY` | `"1e3a58fb24de413c9873542fc5667a25"` | 動態提取失敗時的備用 appKey |
| `FALLBACK_CV` | `"137"` | 動態提取失敗時的備用 cv |
| `MAX_API_RETRIES` | `3` | API 呼叫最大重試次數 |
| `API_TIMEOUT` | `30` | API 請求超時（秒） |
| `DOWNLOAD_TIMEOUT` | `60` | 圖片下載超時（秒） |
| `RETRY_BACKOFF` | `2` | 退避底數（2ⁿ 秒） |

### 新增異常類別

| 類別 | 用途 |
|---|---|
| `ApiError` | API 回應非零 Code，攜帶 `code` 和 `msg` |
| `SiteChangeError` | SPA HTML 結構改變，無法提取預期欄位 |

### 新增函數

| 函數 | 用途 |
|---|---|
| `_api_call(url, payload)` | 統一 API 呼叫：重試、Code 9 處理、錯誤轉換 |
| `_fetch_cv()` | 取得 cv（優先快取 → 動態提取 → 備用值） |
| `_get_app_key()` | 取得 appKey（優先快取 → 動態提取 → 備用值） |
| `_fetch_spa_version()` | 從 SPA HTML 提取版本號 + JS bundle URL |
| `_fetch_app_key(js_url)` | 從 JS bundle 提取 appKey |
| `build_parser()` | 建構 argparse 解析器 |
| `read_urls_from_file(path)` | 從文字檔讀取 URL 列表 |
| `interactive_mode()` | 無引數時的互動式輸入模式 |
| `main()` | CLI 入口點 |

### 測試擴展

測試數量從 **33** 增加至 **60**：

| 新增測試類別 | 數量 | 涵蓋範圍 |
|---|---|---|
| `TestApiCall` | 7 | 成功、重試、最大重試、ak 重生、Code 9 快取失效、連線退避、超時退避 |
| `TestFetchCv` | 2 | HTML 提取、網路錯誤降級 |
| `TestGetAppKey` | 2 | JS 提取、缺 key 降級 |
| `TestFetchSpaVersion` | 2 | 版本解析、SiteChangeError |
| `TestDownloadImage` (新增案例) | +2 | 連線重試、超時重試 |
| `TestFetchAllPhotos` (新增案例) | +1 | API 錯誤時停止分頁 |
| `TestDownloadAggAlbums` (新增案例) | +1 | API 錯誤處理 |
| `TestDispatchUrl` | 5 | 各域名分派、不支援域名、空 URL |
| `TestArgparse` | 5 | 位置引數、多 URL、output flag、file flag、無引數預設 |

---

## [0.1.0] — Initial Release

初始版本，支援 `live.pailixiang.com` 新 API。

- 反向工程 SPA 後端 API（3 個端點 + ak 認證演算法）
- 聚合頁（g-前綴）和單一相冊（a-前綴）下載
- ThreadPoolExecutor 8 執行緒並行下載
- 全繁體中文輸出
- 33 單元測試
- 舊版 `www.pailixiang.com` 支援保留

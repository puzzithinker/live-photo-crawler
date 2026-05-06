# Improvement Report

## Overview

This report documents the improvements made to the live-photo-crawler project to support the new `live.pailixiang.com` domain, modernize the codebase, and harden the crawler against site changes and network failures.

---

## 1. New URL Support: `live.pailixiang.com`

### Problem

The original crawler only supported `www.pailixiang.com` (server-rendered HTML pages). The provider has migrated to a new domain `live.pailixiang.com` which serves a Vue.js SPA — the page source contains no album data, only a `<div id="app">` shell. The old BeautifulSoup-based scraping approach is completely non-functional for this new domain.

### Solution

Reverse-engineered the SPA's backend API by:

1. Loading the page in a headless browser (Playwright) and intercepting network requests
2. Extracting the JavaScript bundle URL (`abms.pailixiang.com/2.1.35/js/index.69a681e1.js`)
3. Finding the API base URL (`mapi.pailixiang.com/plx`) and the `appKey` embedded in the JS
4. Analyzing the `ak` generation algorithm from the minified code
5. Probing the three API endpoints discovered via browser network capture

### Discovered API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/plx/WapAgg/AggGetView` | POST | Fetch aggregation page (event with multiple sub-albums) |
| `/plx/WapAbm/AlbumGetView` | POST | Fetch single album metadata |
| `/plx/WapAbm/AlbumSearchPhoto` | POST | Fetch paginated photo list within an album |

### `ak` Authentication

Every request requires an `ak` token. The generation algorithm was extracted from the SPA's minified JavaScript:

```javascript
// Original minified JS:
let t = Array.from(appKey), n = "";
for (let o = 0; o < 3; o++) {
    let e = Math.floor(10 * Math.random());
    n += e;
    t[e + 15] = t[e];
}
e.ak = n + t.join("");
```

Reimplemented in Python:

```python
def _generate_ak() -> str:
    t = list(APP_KEY)
    prefix = ""
    for _ in range(3):
        e = random.randint(0, 9)
        prefix += str(e)
        t[e + 15] = t[e]
    return prefix + "".join(t)
```

### URL Pattern Handling

The new domain uses two URL patterns:

| Pattern | Code Prefix | Example | Behavior |
|---|---|---|---|
| `/album/main/gXXXXXX` | `g` | `g113328594` | Aggregation page → download all sub-albums into subdirectories |
| `/album/aXXXXXX` | `a` | `a12096096366` | Single album → download photos directly |

Regex-based routing (`/g\d+` and `/a\d+`) avoids false matches — e.g., `/album/` contains "a" but won't trigger the album pattern because there are no digits after it.

### Aggregation Page Flow

Aggregation pages represent events (e.g., a conference) containing multiple photo albums (e.g., per photographer or session). The crawler:

1. Calls `AggGetView` with the numeric ID (stripped of `g` prefix)
2. Extracts all `AlbumCode` values (e.g., `a12096096366`) from `ModuleList[].ItemList[]`
3. For each sub-album, creates a filesystem-safe subdirectory named after the album
4. Downloads all photos from each sub-album

---

## 2. Performance: Concurrent Downloads

### Before

Images were downloaded sequentially — one at a time. For an album with 666 photos at ~10MB each, the bottleneck was network I/O wait time per image.

### After

Images are downloaded in parallel using `ThreadPoolExecutor(max_workers=8)`:

```python
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {}
    for idx, photo in enumerate(all_photos, start=1):
        filepath = os.path.join(store_path, photo["Name"])
        futures[executor.submit(_download_image, photo["DownloadImageUrl"], filepath)] = (idx, photo["Name"])

    for future in as_completed(futures):
        if future.result():
            success += 1
        print(f"\r下載進度: {success}/{total}", end="", flush=True)
```

### Design Decisions

| Decision | Rationale |
|---|---|
| Collect all URLs first, then download | Prevents interleaving API pagination with I/O — cleaner error handling |
| 8 workers | Balances throughput vs. server rate limiting — no `429` errors observed in testing |
| `as_completed` for progress | Shows real-time progress rather than waiting for all to finish |
| Sequential sub-album downloads | Sub-album API calls are fast (~200ms); the bottleneck is photo I/O, not metadata |

### API Pagination

Tested the maximum batch size for `AlbumSearchPhoto`:

| SearchCount | Actual Results |
|---|---|
| 80 | 80 |
| 200 | 80 |
| 500 | 80 |

The server caps at 80 regardless of the requested count. The crawler paginates automatically at 80 photos per page.

---

## 3. Traditional Chinese

### Before

Mixed Simplified Chinese in print statements:

```
正在下载第1张 - 文件名:xxx     # 下载 = Simplified
无法从URL中提取相册编号          # 无法, 编号 = Simplified
```

Also a typo: `正在下栽` (下栽 ≠ 下載) in the original photoplus code.

### After

All user-facing Chinese output converted to Traditional Chinese:

```
正在下載第1張 - 檔案名:xxx     # 下載, 檔案名 = Traditional
無法從URL中提取相冊編號          # 無法, 相冊, 編號 = Traditional
```

Full conversion table for changes in `core/pailixiang.py` and `main.py`:

| Simplified | Traditional | Context |
|---|---|---|
| 下载 | 下載 | Download status messages |
| 下载失败 | 下載失敗 | Error message |
| 相册 | 相冊 | Album label |
| 编号 | 編號 | Code/ID label |
| 聚合页 | 聚合頁 | Aggregation page |
| 活动 | 活動 | Event name |
| 无法 | 無法 | Error messages |
| 识别 | 辨識 | URL format error |
| 文件名 | 檔案名 | Filename label |
| 正在下栽 → 下載 | 下載 | Typo fix + Traditional |
| 没有 → 沒有 | 沒有 | "No photos found" |
| 张 → 張 | 張 | Photo counter |
| 完成 → 完成 | 完成 (same) | — |
| 进度 → 進度 | 進度 | Progress display |
| 支持 → 支援 | 支援 | "Supported domain" |
| 默认 → 預設 | 預設 | Default values |
| 储存 → 儲存 | 儲存 | Storage path |
| 输入 → 輸入 | 輸入 | Input prompts |
| 请 → 請 | 請 | Polite requests |
| 处理 → 處理 | 處理 | Processing status |

---

## 4. Unit Tests

### Before

No tests existed. Changes to API logic, URL parsing, or download behavior were unverified.

### After

60 tests across 2 test files with full HTTP mocking (`unittest.mock.patch`):

**`tests/test_pailixiang.py` — 46 tests**

| Test Class | Tests | What It Verifies |
|---|---|---|
| `TestGenerateAk` | 4 | Output length = 3 + len(APP_KEY), first 3 chars are digits, randomness across calls, positions 0-14 of APP_KEY are preserved |
| `TestBuildPayload` | 4 | All 7 required fields present, `pid` set correctly, kwargs merge correctly, `ak` is a non-empty string |
| `TestDownloadImage` | 4 | Successful write to disk, network error returns False, `ConnectionError` retry, `Timeout` retry |
| `TestApiCall` | 7 | Success path, retry on error, max retries exhausted, `ak` regenerated per attempt, Code 9 cache invalidation + re-fetch, `ConnectionError` exponential backoff, `Timeout` exponential backoff |
| `TestFetchCv` | 2 | HTML version extraction, fallback to `FALLBACK_CV` on network error |
| `TestGetAppKey` | 2 | JS bundle extraction, fallback to `FALLBACK_APP_KEY` if key missing |
| `TestFetchSpaVersion` | 2 | Version string parsing (`2.1.37` → `cv=137`), `SiteChangeError` on no match |
| `TestApiAggGetView` | 2 | `g` prefix stripped from ID, multiple `g` chars stripped |
| `TestApiAlbumGetView` | 1 | `a` prefix stripped from ID |
| `TestApiAlbumSearchPhoto` | 1 | Default pagination: `StartIndex=1`, `SearchCount=80` |
| `TestFetchAllPhotos` | 4 | Single page (1 API call), multi-page (2 API calls), empty album (0 results), stops on `ApiError` |
| `TestDownloadAggAlbums` | 3 | g-code extracted from URL, API error handling, invalid URL returns None |
| `TestDownloadSingleAlbum` | 2 | a-code extracted from URL, invalid URL returns None |
| `TestUrlParsingRegex` | 3 | `/g\d+` matches g-URLs, `/a\d+` matches a-URLs, no false matches from `/album/` path segment |

**`tests/test_main.py` — 14 tests**

| Test Class | Tests | What It Verifies |
|---|---|---|
| `TestLivePailixiangRouting` | 4 | g-URL → `download_agg_albums`, a-URL → `download_single_album`, unknown path → no call, query params stripped |
| `TestDispatchUrl` | 5 | live.pailixiang.com → correct handler, www.pailixiang.com → legacy, photoplus → photoplus_init, unsupported domain → error, empty URL → skip |
| `TestDomainRouting` | 3 | Hostname extraction for all 3 supported domains |
| `TestPhotoplusInit` | 1 | Delegation to `photoplus_dl` |
| `TestPailixiangInit` | 1 | Query string stripping before delegation |
| `TestArgparse` | 5 | Positional URL parsing, multiple URLs, `-o` output flag, `-f` file flag, no-args → interactive mode |

### Test Strategy

- All HTTP calls are mocked — tests run instantly with no network dependency
- API request payloads are inspected to verify correct parameter passing
- URL parsing is tested with both valid and invalid inputs
- Edge cases: empty albums, multi-page pagination, network failures, API errors
- Retry logic tested with mock side effects for consecutive failures
- Code 9 scenario tested with cache invalidation verification

---

## 5. CLI: argparse Command Line Interface

### Before

The only way to use the crawler was interactive `input()` prompts:

```python
store_path = input("请输入储存路径 (默认: ./res): ")
url = input("请输入即时照片URL: ")
```

This required manual intervention every run, couldn't be scripted, and only supported one URL per invocation.

### After

Full `argparse`-based CLI with batch support:

```bash
# Single URL
python main.py https://live.pailixiang.com/album/main/g113328594

# Custom output path
python main.py -o /path/to/photos url1 url2

# Batch from file
python main.py -f urls.txt

# No arguments → interactive mode (backward compatible)
python main.py
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--output` | `-o` | `./res` | Photo storage path |
| `--file` | `-f` | — | Read URLs from file (one per line, `#` comments) |

### Design Decisions

| Decision | Rationale |
|---|---|
| Positional URL args | Most natural CLI usage — no flag needed for the primary input |
| `-f` for file input | Enables batch processing without shell scripting |
| Interactive fallback | Preserves backward compatibility for existing users |
| Per-URL separator line | Visual clarity when processing multiple URLs |

---

## 6. Dynamic Configuration & Version Resilience

### Problem

The initial implementation hardcoded `cv="135"` and `appKey="1e3a58fb24de413c9873542fc5667a25"`. When the SPA updated to v2.1.37 (requiring `cv=137`), the API returned `{"Code": 9, "Msg": "有新版本需要刷新页面", "Data": null}`. The code tried to access `Data["Entity"]` on `null`, causing `TypeError: 'NoneType' object is not subscriptable`.

### Solution: Dynamic Extraction

Both `cv` and `appKey` are now extracted dynamically from the SPA at runtime:

1. **`_fetch_spa_version()`** — Fetches `https://live.pailixiang.com/` HTML, extracts JS bundle URL via regex
2. **`_fetch_app_key(js_url)`** — Fetches the JS bundle, extracts `appKey` via regex
3. **`_fetch_cv()`** — Orchestrates both calls, caches results in module-level variables
4. **`_get_app_key()`** — Returns cached or freshly extracted appKey

Fallback values (`FALLBACK_CV = "137"`, `FALLBACK_APP_KEY = "..."`) are used when extraction fails (network error, site structure change).

### Solution: Code 9 Auto-Recovery

When the API returns `Code: 9` (version expired):

1. `_CACHED_CV` and `_CACHED_APP_KEY` are set to `None` (invalidate cache)
2. `_fetch_cv()` is called again to re-extract from the live SPA
3. The API call is retried with the new `cv` and `appKey`
4. Up to 3 retry attempts with regenerated `ak` each time

### Solution: Site Change Detection

`SiteChangeError` is raised when the SPA HTML structure no longer matches expected patterns (e.g., JS bundle URL format changed, `appKey` no longer in JS). This provides a clear signal that the crawler needs updating, rather than silently failing or producing cryptic errors.

---

## 7. Network Resilience & Error Handling

### Before

- No request timeouts — a hung connection would block indefinitely
- No retry logic — any transient error was fatal
- A single photo download failure would kill the entire batch
- API errors were unhandled — direct dict access on potentially `null` data

### After

| Scenario | Handling |
|---|---|
| API returns `Code: 9` | Auto-invalidate cv/appKey cache, re-fetch from SPA, retry |
| API returns non-zero Code | `ApiError` raised with code and message |
| `ConnectionError` | Retry with exponential backoff (2s, 4s), up to 3 attempts |
| `Timeout` | Retry with exponential backoff, up to 3 attempts |
| Per-photo download failure | Isolated — `_download_image()` retries 3x then returns `False`, batch continues |
| Failed photo files | Listed at end of album download with `✗` marker |
| Network error during cv/appKey extraction | Falls back to hardcoded values with warning |
| SPA HTML structure changes | `SiteChangeError` with descriptive message |

### Key Constants

| Constant | Value | Purpose |
|---|---|---|
| `MAX_API_RETRIES` | 3 | Max retry attempts for API calls and image downloads |
| `API_TIMEOUT` | 30 | Request timeout for API calls (seconds) |
| `DOWNLOAD_TIMEOUT` | 60 | Request timeout for image downloads (seconds) |
| `RETRY_BACKOFF` | 2 | Exponential backoff base (2^n seconds) |

---

## 8. Code Structure Changes

### `main.py`

Completely restructured from interactive prompts to argparse CLI:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="即時照片圖床爬取工具 — 支援拍立享 (pailixiang) 和 photoplus",
    )
    parser.add_argument("urls", nargs="*", help="一個或多個相冊URL")
    parser.add_argument("-o", "--output", default="./res", help="照片儲存路徑")
    parser.add_argument("-f", "--file", help="從檔案讀取URL列表")
    return parser
```

New functions:

| Function | Purpose |
|---|---|
| `build_parser()` | Construct argparse parser with CLI flags |
| `read_urls_from_file(filepath)` | Read URL list from text file |
| `interactive_mode()` | Fallback interactive input (no-args) |
| `main()` | CLI entry point — parse args, dispatch URLs |

Modified function:

| Function | Change |
|---|---|
| `dispatch_url()` | Added empty URL guard, unsupported domain error in Traditional Chinese |
| `live_pailixiang_init()` | Query params stripped before dispatch |

### `core/pailixiang.py`

New public functions:

| Function | Purpose |
|---|---|
| `download_agg_albums(url, store_path)` | Download all sub-albums from a g-prefixed aggregation page |
| `download_single_album(url, store_path)` | Download photos from a single a-prefixed album |

New internal functions:

| Function | Purpose |
|---|---|
| `_api_call(url, payload)` | Unified API call with retry, Code 9 handling, error conversion |
| `_generate_ak()` | Generate per-request authentication token |
| `_build_payload(pid, **kwargs)` | Build common API request payload with `ak` |
| `_fetch_cv()` | Get client version (cache → dynamic → fallback) |
| `_get_app_key()` | Get app key (cache → dynamic → fallback) |
| `_fetch_spa_version()` | Extract version string + JS bundle URL from SPA HTML |
| `_fetch_app_key(js_url)` | Extract appKey from JS bundle |
| `_api_agg_get_view(code)` | Call AggGetView API |
| `_api_album_get_view(code)` | Call AlbumGetView API |
| `_api_album_search_photo(album_id, start_index, count)` | Call AlbumSearchPhoto API |
| `_fetch_all_photos(album_id)` | Paginate through all photo pages |
| `_download_album_by_code(album_code, store_path)` | Orchestrate album download with concurrency |
| `_download_image(url, filepath)` | Download single image with retry and error handling |

New exception classes:

| Class | Purpose |
|---|---|
| `ApiError` | API response error (non-zero Code), carries `code` and `msg` |
| `SiteChangeError` | SPA HTML structure changed, cannot extract expected fields |

Legacy function `download_all_images()` preserved for `www.pailixiang.com` support.

---

## Summary

| Category | Before | After |
|---|---|---|
| Pailixiang URL support | `www.pailixiang.com` only (HTML scraping) | `live.pailixiang.com` (g-prefix + a-prefix) + legacy |
| Download concurrency | Sequential (1 image at a time) | 8 parallel workers via ThreadPoolExecutor |
| Download progress | Per-image print | Live counter: `下載進度: 42/666` |
| Chinese locale | Mixed Simplified + typo | Consistent Traditional Chinese |
| Test coverage | 0 tests | 60 tests with full HTTP mocking |
| API authentication | N/A (HTML scraping) | Reverse-engineered `ak` generation from SPA JS |
| CLI interface | Interactive `input()` prompts only | argparse CLI + batch file + interactive fallback |
| Configuration | Hardcoded `cv` and `appKey` | Dynamic extraction from SPA + fallback values |
| Version expiry | Fatal crash (`NoneType` error) | Auto-recovery: cache invalidation + re-fetch + retry |
| Network errors | Fatal — no timeout, no retry | Timeouts (30s/60s) + 3x retry with exponential backoff |
| Download failures | One failure kills the batch | Per-photo isolation + failure summary |
| Site changes | Silent failure or crash | `SiteChangeError` with descriptive message |

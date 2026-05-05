# Improvement Report

## Overview

This report documents the improvements made to the live-photo-crawler project to support the new `live.pailixiang.com` domain and modernize the codebase.

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

---

## 4. Unit Tests

### Before

No tests existed. Changes to API logic, URL parsing, or download behavior were unverified.

### After

33 tests across 2 test files with full HTTP mocking (`unittest.mock.patch`):

**`tests/test_pailixiang.py` — 25 tests**

| Test Class | Tests | What It Verifies |
|---|---|---|
| `TestGenerateAk` | 4 | Output length = 3 + len(APP_KEY), first 3 chars are digits, randomness across calls, positions 0-14 of APP_KEY are preserved |
| `TestBuildPayload` | 4 | All 7 required fields present, `pid` set correctly, kwargs merge correctly, `ak` is a non-empty string |
| `TestDownloadImage` | 2 | Successful write to disk, graceful `False` return on network error |
| `TestApiAggGetView` | 2 | `g` prefix stripped from ID, multiple `g` chars stripped |
| `TestApiAlbumGetView` | 1 | `a` prefix stripped from ID |
| `TestApiAlbumSearchPhoto` | 1 | Default pagination: `StartIndex=1`, `SearchCount=80` |
| `TestFetchAllPhotos` | 3 | Single page (1 API call), multi-page (2 API calls), empty album (0 results) |
| `TestDownloadAggAlbums` | 2 | g-code extracted from URL, invalid URL returns None |
| `TestDownloadSingleAlbum` | 2 | a-code extracted from URL, invalid URL returns None |
| `TestUrlParsingRegex` | 3 | `/g\d+` matches g-URLs, `/a\d+` matches a-URLs, no false matches from `/album/` path segment |

**`tests/test_main.py` — 8 tests**

| Test Class | Tests | What It Verifies |
|---|---|---|
| `TestLivePailixiangRouting` | 4 | g-URL → `download_agg_albums`, a-URL → `download_single_album`, unknown path → no call, query params stripped |
| `TestDomainRouting` | 3 | Hostname extraction for all 3 supported domains |
| `TestPhotoplusInit` | 1 | Delegation to `photoplus_dl` |
| `TestPailixiangInit` | 1 | Query string stripping before delegation |

### Test Strategy

- All HTTP calls are mocked — tests run instantly with no network dependency
- API request payloads are inspected to verify correct parameter passing
- URL parsing is tested with both valid and invalid inputs
- Edge cases: empty albums, multi-page pagination, network failures

---

## 5. Code Structure Changes

### `main.py`

Added `live.pailixiang.com` domain handler with regex-based URL classification:

```python
def live_pailixiang_init(url: str, store_path: str):
    path = urlparse(url).path
    if re.search(r"/g\d+", path):
        download_agg_albums(url.split("?")[0], store_path)
    elif re.search(r"/a\d+", path):
        download_single_album(url.split("?")[0], store_path)
```

### `core/pailixiang.py`

New public functions added:

| Function | Purpose |
|---|---|
| `download_agg_albums(url, store_path)` | Download all sub-albums from a g-prefixed aggregation page |
| `download_single_album(url, store_path)` | Download photos from a single a-prefixed album |

New internal functions:

| Function | Purpose |
|---|---|
| `_generate_ak()` | Generate per-request authentication token |
| `_build_payload(pid, **kwargs)` | Build common API request payload with `ak` |
| `_api_agg_get_view(code)` | Call AggGetView API |
| `_api_album_get_view(code)` | Call AlbumGetView API |
| `_api_album_search_photo(album_id, start_index, count)` | Call AlbumSearchPhoto API |
| `_fetch_all_photos(album_id)` | Paginate through all photo pages |
| `_download_album_by_code(album_code, store_path)` | Orchestrate album download with concurrency |
| `_download_image(url, filepath)` | Download single image with error handling |

Legacy function `download_all_images()` preserved for `www.pailixiang.com` support.

---

## Summary

| Category | Before | After |
|---|---|---|
| Pailixiang URL support | `www.pailixiang.com` only (HTML scraping) | `live.pailixiang.com` (g-prefix + a-prefix) + legacy |
| Download concurrency | Sequential (1 image at a time) | 8 parallel workers via ThreadPoolExecutor |
| Download progress | Per-image print | Live counter: `下載進度: 42/666` |
| Chinese locale | Mixed Simplified + typo | Consistent Traditional Chinese |
| Test coverage | 0 tests | 33 tests with full HTTP mocking |
| API authentication | N/A (HTML scraping) | Reverse-engineered `ak` generation from SPA JS |

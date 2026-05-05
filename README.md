# live-photo-crawler

針對常見的線下比賽即時照片圖床的影像下載腳本

> 你是否苦於沒辦法將比賽過程中大家的醜照一股腦下載下來
>
> 你是否還在手動一張張將大家的醜照手動下載下來
>
> 現在好時代來了，通過此腳本，你可以一股腦將大家的醜照全部下載下來慢慢做表情包了！！！
>
> --> 此項目針對各類比賽中的即時圖床的影像爬取，請勿用於非法用途或惡意攻擊 <--

## 支持的服務提供商

| Provider | Domain | URL Format | Description |
|---|---|---|---|
| 拍立享照片直播 | `live.pailixiang.com` | `/album/main/gXXXXXX` | Aggregation page (multiple sub-albums) |
| 拍立享照片直播 | `live.pailixiang.com` | `/album/aXXXXXX` | Single album |
| 拍立享照片直播 | `www.pailixiang.com` | Server-rendered pages | Legacy (old site) |
| photoplus | `live.photoplus.cn` | `/live/{id}` | Activity-based photo albums |

## Quick Start

```bash
pip install requests beautifulsoup4

python main.py
```

The script will prompt for:

1. **Store path** — where photos will be saved (default: `./res`)
2. **Live photos URL** — paste the URL from the service provider

### Example URLs

```
https://live.pailixiang.com/album/main/g113328594    # Aggregation page
https://live.pailixiang.com/album/a12096096366       # Single album
https://www.pailixiang.com/Album/Albums?id=XXX        # Legacy
https://live.photoplus.cn/live/12345                  # photoplus
```

## Architecture

```
live-photo-crawler/
├── main.py                  # Entry point — URL routing by domain
├── core/
│   ├── pailixiang.py        # Pailixiang API client (new + legacy)
│   └── photoplus.py         # Photoplus API client
├── tests/
│   ├── test_pailixiang.py   # 25 tests — API, ak generation, URL parsing
│   └── test_main.py         # 8 tests — domain routing, delegation
└── README.md
```

## How It Works

### Pailixiang (live.pailixiang.com) — New API

The new `live.pailixiang.com` site is a Vue SPA that renders client-side. The crawler bypasses rendering by calling the backend API directly. Three endpoints were reverse-engineered from the SPA's JavaScript bundle:

| Endpoint | Purpose | Key Request Fields |
|---|---|---|
| `POST /plx/WapAgg/AggGetView` | Aggregation page metadata | `ID` (numeric code), `pid="aggview"` |
| `POST /plx/WapAbm/AlbumGetView` | Album metadata | `ID` (numeric code), `pid="albumview"` |
| `POST /plx/WapAbm/AlbumSearchPhoto` | Paginated photo list | `AlbumID` (internal ID), `StartIndex`, `SearchCount=80` |

Base URL: `https://mapi.pailixiang.com/plx`

#### Authentication (`ak` field)

Every API request requires an `ak` parameter generated client-side. The algorithm was extracted from the SPA's minified JavaScript:

```python
def _generate_ak() -> str:
    t = list(APP_KEY)        # APP_KEY = "1e3a58fb24de413c9873542fc5667a25"
    prefix = ""
    for _ in range(3):
        e = random.randint(0, 9)
        prefix += str(e)
        t[e + 15] = t[e]    # swap position (e+15) with position e
    return prefix + "".join(t)
```

This produces a 3-digit random prefix + the (slightly permuted) app key. Each call produces a different `ak`, but the server accepts any valid permutation.

#### Pagination

The photo list API caps results at **80 per request** regardless of `SearchCount`. The crawler automatically paginates:

```python
def _fetch_all_photos(album_id: str) -> list:
    all_photos = []
    page = 1
    while True:
        start = (page - 1) * PAGE_SIZE + 1   # PAGE_SIZE = 80
        photos = _api_album_search_photo(album_id, start_index=start)
        if not photos:
            break
        all_photos.extend(photos)
        if len(photos) < PAGE_SIZE:
            break
        page += 1
    return all_photos
```

#### Aggregation Pages

A `g`-prefixed URL (e.g., `g113328594`) represents an event with multiple sub-albums. The flow is:

1. `AggGetView` → retrieve event title + list of sub-albums (each with `AlbumCode` like `a12096096366`)
2. For each sub-album → `AlbumGetView` → get album metadata + internal `ID`
3. For each album → `AlbumSearchPhoto` → fetch all photo URLs
4. Download all photos concurrently

Sub-albums are saved into separate subdirectories named after the album.

### Pailixiang (www.pailixiang.com) — Legacy API

The old site uses server-rendered HTML with embedded `albumId`. The crawler:

1. Fetches the HTML page with `requests`
2. Parses `<script>` tags with BeautifulSoup to extract `albumId`
3. Calls `AlbumDetail.ashx?t=1` with `POST` data `{start, len, albumId}` to get photo info
4. Downloads each photo sequentially

### Photoplus (live.photoplus.cn)

Uses a signed API:

1. Build params with `activityNo`, timestamp `_t`, etc.
2. Sort keys alphabetically, concatenate as `key=value&...`
3. Append salt `"laxiaoheiwu"` and compute MD5 → `_s` signature
4. `GET /pic/pics` with signed params → photo list
5. Download each photo sequentially (with 2-second delay between downloads)

## Concurrency

The new pailixiang downloader uses `ThreadPoolExecutor` with 8 workers for parallel image downloads:

```python
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {}
    for idx, photo in enumerate(all_photos, start=1):
        filepath = os.path.join(store_path, photo["Name"])
        futures[executor.submit(_download_image, photo["DownloadImageUrl"], filepath)] = (idx, photo["Name"])

    for future in as_completed(futures):
        idx, name = futures[future]
        if future.result():
            success += 1
        print(f"\r下載進度: {success}/{total}", end="", flush=True)
```

All photo URLs are collected first via `_fetch_all_photos()`, then downloaded in parallel. Progress is displayed as `下載進度: 42/666`.

## Testing

```bash
python -m pytest tests/ -v
```

33 tests with full HTTP mocking:

| Test Class | Count | Coverage |
|---|---|---|
| `TestGenerateAk` | 4 | Length, digit prefix, randomness, base preservation |
| `TestBuildPayload` | 4 | Required fields, pid, kwargs override, ak type |
| `TestDownloadImage` | 2 | Success + network error |
| `TestApiAggGetView` | 2 | g-prefix stripping, multi-g stripping |
| `TestApiAlbumGetView` | 1 | a-prefix stripping |
| `TestApiAlbumSearchPhoto` | 1 | Default pagination params |
| `TestFetchAllPhotos` | 3 | Single page, multi-page, empty album |
| `TestDownloadAggAlbums` | 2 | URL extraction, invalid URL |
| `TestDownloadSingleAlbum` | 2 | URL extraction, invalid URL |
| `TestUrlParsingRegex` | 3 | g/a patterns, no false matches |
| `TestLivePailixiangRouting` | 4 | g→agg, a→single, unknown, query strip |
| `TestDomainRouting` | 3 | Hostname resolution |
| `TestPhotoplusInit` | 1 | Delegation |
| `TestPailixiangInit` | 1 | Query stripping |

## Dependencies

- `requests` — HTTP client
- `beautifulsoup4` — HTML parsing (legacy pailixiang only)

## References

- photoplus parsing referenced from: [photoplus downloader By yufeiyohi](https://github.com/yufeiyohi/photoplus)

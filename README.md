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
```

### Command Line

```bash
# Single URL
python main.py https://live.pailixiang.com/album/main/g113328594

# Custom output path
python main.py -o /path/to/photos https://live.pailixiang.com/album/main/g113328594

# Multiple URLs at once
python main.py url1 url2 url3

# Batch from file (one URL per line, # comments supported)
python main.py -f urls.txt

# Combine file + direct URLs
python main.py -f urls.txt -o ./output https://live.pailixiang.com/album/main/g123

# No arguments → interactive mode (original behavior)
python main.py
```

### CLI Flags

| Flag | Short | Default | Description |
|---|---|---|---|
| `--output` | `-o` | `./res` | Photo storage path |
| `--file` | `-f` | — | Read URLs from file (one per line) |

### Example URLs

```
https://live.pailixiang.com/album/main/g113328594?from=singlemessage  # Aggregation page (query params auto-stripped)
https://live.pailixiang.com/album/a12096096366                         # Single album
https://www.pailixiang.com/Album/Albums?id=XXX                          # Legacy
https://live.photoplus.cn/live/12345                                     # photoplus
```

## Architecture

```
live-photo-crawler/
├── main.py                  # Entry point — argparse CLI + URL routing
├── core/
│   ├── pailixiang.py        # Pailixiang API client (new + legacy)
│   └── photoplus.py         # Photoplus API client
├── tests/
│   ├── test_pailixiang.py   # 46 tests — API, ak generation, retries, site resilience
│   └── test_main.py         # 14 tests — CLI, domain routing, dispatch
├── README.md
├── IMPROVEMENTS.md          # Improvement report (initial changes)
└── CHANGELOG.md             # Fix log (post-release bug fixes)
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

#### Dynamic Configuration

Both `cv` (client version) and `appKey` are extracted dynamically from the SPA at runtime:

1. Fetch `https://live.pailixiang.com/` HTML
2. Extract JS bundle URL (e.g., `abms.pailixiang.com/2.1.37/js/index.xxx.js`)
3. Parse `cv` from the version string (e.g., `2.1.37` → `cv=137`)
4. Fetch the JS bundle, extract `appKey` via regex `appKey:"([0-9a-f]{30,})"`

If extraction fails, hardcoded fallback values are used. When the API returns `Code: 9` ("version expired"), the cache is invalidated and configuration is re-fetched automatically.

#### Authentication (`ak` field)

Every API request requires an `ak` parameter generated client-side. The algorithm was extracted from the SPA's minified JavaScript:

```python
def _generate_ak() -> str:
    t = list(app_key)
    prefix = ""
    for _ in range(3):
        e = random.randint(0, 9)
        prefix += str(e)
        t[e + 15] = t[e]
    return prefix + "".join(t)
```

This produces a 3-digit random prefix + the (slightly permuted) app key. Each call produces a different `ak`, but the server accepts any valid permutation.

#### Pagination

The photo list API caps results at **80 per request** regardless of `SearchCount`. The crawler automatically paginates via `_fetch_all_photos()`.

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

Uses a signed API with MD5 salt-based authentication. Downloads photos sequentially with a 2-second delay.

## Concurrency

The new pailixiang downloader uses `ThreadPoolExecutor` with 8 workers for parallel image downloads. All photo URLs are collected first via `_fetch_all_photos()`, then downloaded in parallel. Progress is displayed as `下載進度: 42/666`.

Failed downloads are isolated — one failure doesn't stop the batch. Failed filenames are listed at the end of each album download.

## Resilience

The crawler is designed to survive common site changes and network issues:

| Scenario | Handling |
|---|---|
| **SPA version bump** | `Code: 9` auto-invalidates `cv`/`appKey` cache and re-fetches from the SPA |
| **`appKey` changes** | Dynamically extracted from the JS bundle; fallback to hardcoded value |
| **SPA HTML structure changes** | `SiteChangeError` raised with descriptive message |
| **API rejects `ak`** | Up to 3 retries with regenerated `ak` per attempt |
| **Network timeout** | 30s for API calls, 60s for image downloads |
| **Connection reset** | Retry with exponential backoff (2s, 4s) on `ConnectionError` and `Timeout` |
| **Per-photo download failure** | Isolated — batch continues, failed files listed at end |
| **Unsupported domain** | Clear error: `不支援的域名: example.com` |

## Testing

```bash
python -m pytest tests/ -v
```

60 tests with full HTTP mocking:

| Test Class | Count | Coverage |
|---|---|---|
| `TestGenerateAk` | 4 | Length, digit prefix, randomness, base preservation |
| `TestBuildPayload` | 4 | Required fields, pid, kwargs override, ak type |
| `TestDownloadImage` | 4 | Success, network error, connection retry, timeout retry |
| `TestApiCall` | 7 | Success, retry on error, max retries, ak regeneration, Code 9 cache invalidation, connection backoff, timeout retry |
| `TestFetchCv` | 2 | HTML extraction, fallback on network error |
| `TestGetAppKey` | 2 | JS extraction, fallback if key missing |
| `TestFetchSpaVersion` | 2 | Version parsing, SiteChangeError on no match |
| `TestApiAggGetView` | 2 | g-prefix stripping, multi-g stripping |
| `TestApiAlbumGetView` | 1 | a-prefix stripping |
| `TestApiAlbumSearchPhoto` | 1 | Default pagination params |
| `TestFetchAllPhotos` | 4 | Single page, multi-page, empty album, stops on API error |
| `TestDownloadAggAlbums` | 3 | URL extraction, API error, invalid URL |
| `TestDownloadSingleAlbum` | 2 | URL extraction, invalid URL |
| `TestUrlParsingRegex` | 3 | g/a patterns, no false matches |
| `TestLivePailixiangRouting` | 4 | g→agg, a→single, unknown, query strip |
| `TestDispatchUrl` | 5 | live.pailixiang, www.pailixiang, photoplus, unsupported domain, empty URL |
| `TestDomainRouting` | 3 | Hostname resolution |
| `TestPhotoplusInit` | 1 | Delegation |
| `TestPailixiangInit` | 1 | Query stripping |
| `TestArgparse` | 5 | Positional URL, multiple URLs, output flag, file flag, no-args default |

## Dependencies

- `requests` — HTTP client
- `beautifulsoup4` — HTML parsing (legacy pailixiang only)

## References

- photoplus parsing referenced from: [photoplus downloader By yufeiyohi](https://github.com/yufeiyohi/photoplus)

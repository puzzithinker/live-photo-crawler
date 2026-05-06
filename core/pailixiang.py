import random
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API_BASE = "https://mapi.pailixiang.com/plx"
FALLBACK_APP_KEY = "1e3a58fb24de413c9873542fc5667a25"
FALLBACK_CV = "137"
PAGE_SIZE = 80
MAX_WORKERS = 8
MAX_API_RETRIES = 3
DOWNLOAD_TIMEOUT = 60
API_TIMEOUT = 30
RETRY_BACKOFF = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://live.pailixiang.com/",
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
}

OLD_API_GETINFO = "https://www.pailixiang.com/Portal/Services/AlbumDetail.ashx?t=1"

_CACHED_CV = None
_CACHED_APP_KEY = None


class ApiError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"API error {code}: {msg}")


class SiteChangeError(Exception):
    def __init__(self, detail: str):
        super().__init__(f"Site structure may have changed: {detail}")


def _fetch_spa_version() -> tuple[str, str]:
    """Fetch SPA HTML and extract version string + JS bundle URL."""
    html = requests.get(
        "https://live.pailixiang.com/",
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=API_TIMEOUT,
    ).text
    match = re.search(r'(abms\.pailixiang\.com/(\d+)\.(\d+)\.(\d+)/js/index\.[0-9a-f]+\.js)', html)
    if not match:
        raise SiteChangeError("Cannot find SPA JS bundle URL in HTML")
    js_url = f"https://{match.group(1)}"
    cv = match.group(3) + match.group(4)
    return cv, js_url


def _fetch_app_key(js_url: str) -> str:
    """Fetch the SPA JS bundle and extract appKey."""
    js_text = requests.get(
        js_url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://live.pailixiang.com/",
            "Accept-Encoding": "gzip, deflate, br",
        },
        timeout=API_TIMEOUT,
    ).text
    match = re.search(r'appKey:"([0-9a-f]{30,})"', js_text)
    if not match:
        raise SiteChangeError("Cannot find appKey in SPA JS bundle")
    return match.group(1)


def _fetch_cv() -> str:
    global _CACHED_CV, _CACHED_APP_KEY
    if _CACHED_CV is not None:
        return _CACHED_CV
    try:
        cv, js_url = _fetch_spa_version()
        _CACHED_CV = cv
        try:
            _CACHED_APP_KEY = _fetch_app_key(js_url)
        except (SiteChangeError, requests.RequestException) as err:
            print(f"警告: 無法動態取得appKey，使用備用值 — {err}")
            _CACHED_APP_KEY = FALLBACK_APP_KEY
        return _CACHED_CV
    except (SiteChangeError, requests.RequestException) as err:
        print(f"警告: 無法動態取得版本號，使用備用值 — {err}")
        _CACHED_CV = FALLBACK_CV
        _CACHED_APP_KEY = FALLBACK_APP_KEY
        return _CACHED_CV


def _get_app_key() -> str:
    global _CACHED_APP_KEY
    if _CACHED_APP_KEY is not None:
        return _CACHED_APP_KEY
    _fetch_cv()
    return _CACHED_APP_KEY


def _generate_ak() -> str:
    app_key = _get_app_key()
    t = list(app_key)
    prefix = ""
    for _ in range(3):
        e = random.randint(0, 9)
        prefix += str(e)
        t[e + 15] = t[e]
    return prefix + "".join(t)


def _build_payload(pid: str, **kwargs) -> dict:
    payload = {
        "ClientType": 0,
        "tt": "",
        "ct": 0,
        "cv": _fetch_cv(),
        "lang": "cn",
        "pid": pid,
        "ak": _generate_ak(),
    }
    payload.update(kwargs)
    return payload


def _api_call(url: str, payload: dict) -> dict:
    last_err = None
    for attempt in range(1, MAX_API_RETRIES + 1):
        payload["ak"] = _generate_ak()
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=API_TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as err:
            last_err = err
            if attempt < MAX_API_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"連線失敗 (嘗試 {attempt}/{MAX_API_RETRIES})，{wait}秒後重試 — {err}")
                time.sleep(wait)
                continue
            raise ApiError(-1, f"連線失敗: {err}")
        except requests.exceptions.Timeout as err:
            last_err = err
            if attempt < MAX_API_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                print(f"請求超時 (嘗試 {attempt}/{MAX_API_RETRIES})，{wait}秒後重試 — {err}")
                time.sleep(wait)
                continue
            raise ApiError(-1, f"請求超時: {err}")
        except requests.RequestException as err:
            raise ApiError(-1, str(err))

        body = resp.json()
        code = body.get("Code", -1)
        if code == 0:
            return body.get("Data")
        if code == 9:
            global _CACHED_CV, _CACHED_APP_KEY
            _CACHED_CV = None
            _CACHED_APP_KEY = None
            if attempt < MAX_API_RETRIES:
                payload["cv"] = _fetch_cv()
                print(f"版本過期 (嘗試 {attempt}/{MAX_API_RETRIES})，已重新取得cv={payload['cv']}")
                continue
        if attempt < MAX_API_RETRIES:
            print(f"API回應錯誤 (嘗試 {attempt}/{MAX_API_RETRIES}): [{code}] {body.get('Msg', '')}")
        else:
            raise ApiError(code, body.get("Msg", "未知錯誤"))
    raise ApiError(-1, f"所有重試失敗: {last_err}")


def _download_image(url: str, filepath: str) -> bool:
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            response = requests.get(
                url,
                stream=True,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Referer": "https://live.pailixiang.com/",
                },
                timeout=DOWNLOAD_TIMEOUT,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            if attempt < MAX_API_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)
                continue
            return False
        except requests.exceptions.Timeout:
            if attempt < MAX_API_RETRIES:
                time.sleep(RETRY_BACKOFF ** attempt)
                continue
            return False
        except requests.RequestException as err:
            return False
        with open(filepath, "wb") as out_file:
            out_file.write(response.content)
        return True
    return False


# ---------- New API (live.pailixiang.com) ----------

def _api_agg_get_view(code: str) -> dict:
    payload = _build_payload(
        pid="aggview",
        ID=code.lstrip("g"),
        SourceType="",
    )
    return _api_call(f"{API_BASE}/WapAgg/AggGetView", payload)


def _api_album_get_view(code: str) -> dict:
    payload = _build_payload(
        pid="albumview",
        ID=code.lstrip("a"),
        AccessType="",
    )
    return _api_call(f"{API_BASE}/WapAbm/AlbumGetView", payload)


def _api_album_search_photo(album_id: str, start_index: int = 1, count: int = PAGE_SIZE) -> list:
    payload = _build_payload(
        pid="albumview",
        AlbumID=album_id,
        GroupID="",
        SearchType=0,
        IsPayDownload=False,
        PhotoSortType=1,
        IsNw=False,
        IsEmbed=False,
        StartIndex=start_index,
        SearchCount=count,
        SortType=1,
        OptTime="",
    )
    return _api_call(f"{API_BASE}/WapAbm/AlbumSearchPhoto", payload)


def _fetch_all_photos(album_id: str) -> list:
    all_photos = []
    page = 1
    while True:
        start = (page - 1) * PAGE_SIZE + 1
        try:
            photos = _api_album_search_photo(album_id, start_index=start)
        except ApiError as err:
            print(f"\n取得照片列表失敗 (頁{page}): {err}")
            break
        if not photos:
            break
        all_photos.extend(photos)
        if len(photos) < PAGE_SIZE:
            break
        page += 1
    return all_photos


def _download_album_by_code(album_code: str, store_path: str):
    if not os.path.exists(store_path):
        os.makedirs(store_path)

    try:
        album_data = _api_album_get_view(album_code)
    except ApiError as err:
        print(f"取得相冊資訊失敗: {err}")
        return
    album_entity = album_data["Entity"]
    album_name = album_entity.get("Title", album_code)
    album_id = album_entity["ID"]
    print(f"相冊: {album_name}")

    all_photos = _fetch_all_photos(album_id)
    if not all_photos:
        print("沒有找到照片。")
        return

    total = len(all_photos)
    print(f"共 {total} 張照片，開始下載...")

    success = 0
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for idx, photo in enumerate(all_photos, start=1):
            filepath = os.path.join(store_path, photo["Name"])
            futures[executor.submit(_download_image, photo["DownloadImageUrl"], filepath)] = (idx, photo["Name"])

        for future in as_completed(futures):
            idx, name = futures[future]
            if future.result():
                success += 1
            else:
                failed.append(name)
            print(f"\r下載進度: {success}/{total}", end="", flush=True)

    print(f"\n下載完成，成功 {success}/{total} 張", end="")
    if failed:
        print(f"，失敗 {len(failed)} 張")
        for name in failed:
            print(f"  ✗ {name}")
    else:
        print()


def download_agg_albums(url: str, store_path: str):
    """Download all sub-albums from an aggregation page (g-prefixed URL).

    URL format: https://live.pailixiang.com/album/main/g113328594
    """
    match = re.search(r"/g(\d+)", url)
    if not match:
        print(f"無法從URL中提取相冊編號: {url}")
        return

    agg_code = match.group(1)
    print(f"聚合頁編號: g{agg_code}")

    try:
        agg_data = _api_agg_get_view(agg_code)
    except ApiError as err:
        print(f"取得聚合頁資訊失敗: {err}")
        return
    entity = agg_data["Entity"]
    print(f"活動: {entity.get('Title', entity.get('Name', 'Unknown'))}")

    module_list = agg_data.get("ModuleList", [])
    if not module_list:
        print("未找到子相冊。")
        return

    sub_albums = []
    for module in module_list:
        for item in module.get("ItemList", []):
            album_code = item.get("AlbumCode", "")
            if album_code:
                album_name = item.get("Name", "").replace("<br />", " ")
                photo_qty = item.get("PhotoQty", 0)
                sub_albums.append((album_code, album_name, photo_qty))

    for album_code, album_name, photo_qty in sub_albums:
        print(f"\n--- 子相冊: {album_name} ({photo_qty}張) [{album_code}] ---")
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', album_name)
        sub_store = os.path.join(store_path, safe_name)
        _download_album_by_code(album_code, sub_store)


def download_single_album(url: str, store_path: str):
    """Download a single album (a-prefixed URL).

    URL format: https://live.pailixiang.com/album/a12096096366
    """
    match = re.search(r"/a(\d+)", url)
    if not match:
        print(f"無法從URL中提取相冊編號: {url}")
        return

    album_code = match.group(1)
    _download_album_by_code(f"a{album_code}", store_path)


# ---------- Old API (www.pailixiang.com) ----------

def download_all_images(url: str, store_path: str):
    """Download all images using the old www.pailixiang.com API (server-rendered)."""
    from bs4 import BeautifulSoup

    if not os.path.exists(store_path):
        os.makedirs(store_path)
    soup_data = BeautifulSoup(requests.get(url, timeout=API_TIMEOUT).text, "html.parser")
    albumId_raw = None
    for node in soup_data.find_all("script"):
        if "albumId" in str(node):
            raw = [i.strip() for i in str(node).split("\n") if "albumId" in i][0].split("{")[1].split("}")[0]
            raw = [i.strip() for i in str(raw).split(",") if "albumId" in i][0]
            albumId_raw = raw.split('"')[1]
    if not albumId_raw:
        print("無法從頁面中提取albumId")
        return
    data = {
        "start": 0,
        "len": 1,
        "albumId": albumId_raw,
    }
    total_count = requests.post(OLD_API_GETINFO, data, timeout=API_TIMEOUT).json()["TotalCount"]
    for i in range(1, total_count):
        data["start"] = i
        image_info = requests.post(OLD_API_GETINFO, data, timeout=API_TIMEOUT).json()["Data"][0]
        image_filename = image_info["Name"]
        image_url = image_info["DownloadImageUrl"]
        print("正在下載第{}張 - 檔案名:{}".format(i, image_filename))
        try:
            response = requests.get(image_url, stream=True, timeout=DOWNLOAD_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as err:
            print("Oops: Something else happened", err)
            return
        with open(os.path.join(store_path, image_filename), "wb") as out_file:
            out_file.write(response.content)

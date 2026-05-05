import random
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API_BASE = "https://mapi.pailixiang.com/plx"
APP_KEY = "1e3a58fb24de413c9873542fc5667a25"
PAGE_SIZE = 80
MAX_WORKERS = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://live.pailixiang.com/",
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
}

OLD_API_GETINFO = "https://www.pailixiang.com/Portal/Services/AlbumDetail.ashx?t=1"


def _generate_ak() -> str:
    t = list(APP_KEY)
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
        "cv": "135",
        "lang": "cn",
        "pid": pid,
        "ak": _generate_ak(),
    }
    payload.update(kwargs)
    return payload


def _download_image(url: str, filepath: str) -> bool:
    try:
        response = requests.get(url, stream=True, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://live.pailixiang.com/",
        })
        response.raise_for_status()
    except requests.RequestException as err:
        print(f"下載失敗: {err}")
        return False
    with open(filepath, "wb") as out_file:
        out_file.write(response.content)
    return True


# ---------- New API (live.pailixiang.com) ----------

def _api_agg_get_view(code: str) -> dict:
    payload = _build_payload(
        pid="aggview",
        ID=code.lstrip("g"),
        SourceType="",
    )
    resp = requests.post(f"{API_BASE}/WapAgg/AggGetView", json=payload, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["Data"]


def _api_album_get_view(code: str) -> dict:
    payload = _build_payload(
        pid="albumview",
        ID=code.lstrip("a"),
        AccessType="",
    )
    resp = requests.post(f"{API_BASE}/WapAbm/AlbumGetView", json=payload, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["Data"]


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
    resp = requests.post(f"{API_BASE}/WapAbm/AlbumSearchPhoto", json=payload, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["Data"]


def _fetch_all_photos(album_id: str) -> list:
    all_photos = []
    page = 1
    while True:
        start = (page - 1) * PAGE_SIZE + 1
        photos = _api_album_search_photo(album_id, start_index=start)
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

    album_data = _api_album_get_view(album_code)
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

    print(f"\n下載完成，成功 {success}/{total} 張")


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

    agg_data = _api_agg_get_view(agg_code)
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
    soup_data = BeautifulSoup(requests.get(url).text, "html.parser")
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
    total_count = requests.post(OLD_API_GETINFO, data).json()["TotalCount"]
    for i in range(1, total_count):
        data["start"] = i
        image_info = requests.post(OLD_API_GETINFO, data).json()["Data"][0]
        image_filename = image_info["Name"]
        image_url = image_info["DownloadImageUrl"]
        print("正在下載第{}張 - 檔案名:{}".format(i, image_filename))
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
        except requests.RequestException as err:
            print("Oops: Something else happened", err)
            return
        with open(os.path.join(store_path, image_filename), "wb") as out_file:
            out_file.write(response.content)

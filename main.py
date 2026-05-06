import argparse
import re
import sys
from urllib.parse import urlparse

from core.photoplus import get_all_images as photoplus_dl
from core.pailixiang import (
    download_all_images as pailixiang_dl,
    download_agg_albums,
    download_single_album,
)


def photoplus_init(id: int, store_path: str):
    photoplus_dl(id, store_path)


def pailixiang_init(url: str, store_path: str):
    pailixiang_dl(url.split("?")[0], store_path)


def live_pailixiang_init(url: str, store_path: str):
    path = urlparse(url).path
    if re.search(r"/g\d+", path):
        download_agg_albums(url.split("?")[0], store_path)
    elif re.search(r"/a\d+", path):
        download_single_album(url.split("?")[0], store_path)
    else:
        print("無法辨識的 live.pailixiang.com URL 格式")


def dispatch_url(url: str, store_path: str):
    url = url.strip()
    if not url:
        return
    url_domain = urlparse(url).hostname
    if not url_domain:
        print(f"無法解析URL: {url}")
        return
    print(f"URL已識別: {url_domain}")
    match url_domain:
        case "live.photoplus.cn":
            parts = urlparse(url).path.split("/")
            photoplus_id = parts[-1] if parts else ""
            if photoplus_id.isnumeric():
                photoplus_init(int(photoplus_id), store_path)
            else:
                print(f"無法從URL中提取photoplus ID: {url}")
        case "www.pailixiang.com":
            pailixiang_init(url, store_path)
        case "live.pailixiang.com":
            live_pailixiang_init(url, store_path)
        case _:
            print(f"不支援的域名: {url_domain}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="即時照片圖床爬取工具 — 支援拍立享 (pailixiang) 和 photoplus",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="一個或多個相冊URL",
    )
    parser.add_argument(
        "-o", "--output",
        default="./res",
        help="照片儲存路徑 (預設: ./res)",
    )
    parser.add_argument(
        "-f", "--file",
        help="從檔案讀取URL列表 (每行一個)",
    )
    return parser


def read_urls_from_file(filepath: str) -> list[str]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        print(f"URL檔案不存在: {filepath}")
        return []


def interactive_mode() -> None:
    store_path = input("請輸入儲存路徑 (預設: ./res): ").strip()
    if not store_path:
        store_path = "./res"
    print(f"儲存路徑: {store_path}")
    url = input("請輸入即時照片URL: ").strip()
    if url:
        dispatch_url(url, store_path)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    store_path = args.output
    urls = list(args.urls)

    if args.file:
        urls.extend(read_urls_from_file(args.file))

    if not urls:
        interactive_mode()
        return

    for url in urls:
        print(f"\n{'='*50}")
        print(f"處理URL: {url}")
        dispatch_url(url, store_path)


if __name__ == "__main__":
    main()

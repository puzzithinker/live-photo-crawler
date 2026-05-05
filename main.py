import re
from urllib.parse import urlparse
from core.photoplus import get_all_images as photoplus_dl
from core.pailixiang import (
    download_all_images as pailixiang_dl,
    download_agg_albums,
    download_single_album,
)

DEBUG = False


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


if __name__ == "__main__":
    store_path = "./res"
    if not DEBUG:
        store_path = input("Enter where will you store photos (default: ./res): ")
        if store_path == "":
            store_path = "./res"
    print("Store path set to: {}".format(store_path))
    url = input("Please input live photos url: ")
    url_domain = urlparse(url).hostname
    print("URL has been identified: {}".format(url_domain))
    match url_domain:
        case "live.photoplus.cn":
            photoplus_id = urlparse(url).path.split("/")[3]
            if photoplus_id.isnumeric():
                photoplus_init(int(photoplus_id), store_path)
        case "www.pailixiang.com":
            pailixiang_init(url.split("?")[0], store_path)
        case "live.pailixiang.com":
            live_pailixiang_init(url.split("?")[0], store_path)

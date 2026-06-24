import re
from unittest.mock import patch, MagicMock
import unittest

from core.pailixiang import (
    _generate_ak,
    _build_payload,
    _download_image,
    _api_agg_get_view,
    _api_album_get_view,
    _api_album_search_photo,
    _api_call,
    _fetch_all_photos,
    _fetch_cv,
    _get_app_key,
    _fetch_spa_version,
    download_agg_albums,
    download_single_album,
    ApiError,
    SiteChangeError,
    FALLBACK_APP_KEY,
    FALLBACK_CV,
    PAGE_SIZE,
    MAX_API_RETRIES,
)


def _mock_ok_response(data):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Code": 0, "Msg": "", "Data": data}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_error_response(code=8, msg="非法请求"):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"Code": code, "Msg": msg, "Data": None}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestGenerateAk(unittest.TestCase):
    def test_length(self):
        ak = _generate_ak()
        self.assertEqual(len(ak), 3 + len(FALLBACK_APP_KEY))

    def test_starts_with_three_digits(self):
        for _ in range(20):
            ak = _generate_ak()
            self.assertTrue(ak[:3].isdigit(), f"Prefix not digits: {ak[:3]}")

    def test_each_call_different(self):
        aks = {_generate_ak() for _ in range(50)}
        self.assertGreater(len(aks), 1, "All generated ak values are identical")

    def test_preserves_app_key_base(self):
        ak = _generate_ak()
        chars = list(ak[3:])
        base = list(FALLBACK_APP_KEY)
        for i in range(15):
            self.assertEqual(chars[i], base[i], f"Char at position {i} changed unexpectedly")


class TestBuildPayload(unittest.TestCase):
    def test_includes_required_fields(self):
        payload = _build_payload(pid="test")
        for key in ("ClientType", "tt", "ct", "cv", "lang", "pid", "ak"):
            self.assertIn(key, payload)

    def test_pid_set_correctly(self):
        payload = _build_payload(pid="aggview")
        self.assertEqual(payload["pid"], "aggview")

    def test_kwargs_override(self):
        payload = _build_payload(pid="test", ID="123", SourceType="")
        self.assertEqual(payload["ID"], "123")
        self.assertEqual(payload["SourceType"], "")

    def test_ak_is_string(self):
        payload = _build_payload(pid="test")
        self.assertIsInstance(payload["ak"], str)
        self.assertTrue(len(payload["ak"]) > 0)


class TestDownloadImage(unittest.TestCase):
    @patch("core.pailixiang.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"fake-image-data"
        mock_get.return_value = mock_resp

        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            result = _download_image("https://example.com/img.jpg", tmp.name)
        self.assertTrue(result)
        with open(tmp.name, "rb") as f:
            self.assertEqual(f.read(), b"fake-image-data")
        import os
        os.unlink(tmp.name)

    @patch("core.pailixiang.requests.get")
    def test_network_error_returns_false(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("timeout")
        result = _download_image("https://example.com/img.jpg", "/tmp/nonexistent.jpg")
        self.assertFalse(result)

    @patch("core.pailixiang.requests.get")
    def test_connection_error_retries(self, mock_get):
        import requests as req
        ok_resp = MagicMock()
        ok_resp.raise_for_status = MagicMock()
        ok_resp.content = b"data"
        mock_get.side_effect = [
            req.exceptions.ConnectionError("reset"),
            ok_resp,
        ]
        result = _download_image("https://example.com/img.jpg", "/tmp/test_retry.jpg")
        self.assertTrue(result)
        self.assertEqual(mock_get.call_count, 2)

    @patch("core.pailixiang.time.sleep")
    @patch("core.pailixiang.requests.get")
    def test_timeout_retries(self, mock_get, mock_sleep):
        import requests as req
        ok_resp = MagicMock()
        ok_resp.raise_for_status = MagicMock()
        ok_resp.content = b"data"
        mock_get.side_effect = [
            req.exceptions.Timeout("timed out"),
            ok_resp,
        ]
        result = _download_image("https://example.com/img.jpg", "/tmp/test_timeout.jpg")
        self.assertTrue(result)
        mock_sleep.assert_called()


class TestApiCall(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_success_returns_data(self, mock_post):
        mock_post.return_value = _mock_ok_response({"Entity": {"Title": "Test"}})
        result = _api_call("https://example.com/api", {"pid": "test", "ak": "old"})
        self.assertEqual(result, {"Entity": {"Title": "Test"}})

    @patch("core.pailixiang.time.sleep")
    @patch("core.pailixiang.requests.post")
    def test_retries_on_error_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            _mock_error_response(8, "非法请求"),
            _mock_ok_response({"Entity": {"Title": "OK"}}),
        ]
        result = _api_call("https://example.com/api", {"pid": "test", "ak": "old"})
        self.assertEqual(result, {"Entity": {"Title": "OK"}})
        self.assertEqual(mock_post.call_count, 2)

    @patch("core.pailixiang.requests.post")
    def test_raises_after_max_retries(self, mock_post):
        mock_post.return_value = _mock_error_response(8, "非法请求")
        with self.assertRaises(ApiError) as ctx:
            _api_call("https://example.com/api", {"pid": "test", "ak": "old"})
        self.assertEqual(ctx.exception.code, 8)
        self.assertEqual(mock_post.call_count, MAX_API_RETRIES)

    @patch("core.pailixiang.requests.post")
    def test_regenerates_ak_on_each_retry(self, mock_post):
        mock_post.side_effect = [
            _mock_error_response(8, "fail1"),
            _mock_error_response(8, "fail2"),
            _mock_ok_response("success"),
        ]
        _api_call("https://example.com/api", {"pid": "test", "ak": "initial"})
        aks_used = []
        for call in mock_post.call_args_list:
            payload = call.kwargs.get("json") or call[1].get("json")
            aks_used.append(payload["ak"])
        self.assertEqual(len(aks_used), 3)
        self.assertNotEqual(aks_used[0], "initial")

    @patch("core.pailixiang.time.sleep")
    @patch("core.pailixiang.requests.post")
    def test_code9_invalidates_cv_cache(self, mock_post, mock_sleep):
        import core.pailixiang as px
        px._CACHED_CV = None
        px._CACHED_APP_KEY = None

        side_effects = [
            _mock_error_response(9, "有新版本需要刷新页面"),
            _mock_ok_response({"ok": True}),
        ]
        mock_post.side_effect = side_effects

        with patch("core.pailixiang._fetch_spa_version", return_value=("138", "https://abms.pailixiang.com/2.1.38/js/index.xxx.js")):
            with patch("core.pailixiang._fetch_app_key", return_value=FALLBACK_APP_KEY):
                result = _api_call("https://example.com/api", {"pid": "test", "ak": "old", "cv": "137"})
        self.assertEqual(result, {"ok": True})

    @patch("core.pailixiang.time.sleep")
    @patch("core.pailixiang.requests.post")
    def test_connection_error_retries_with_backoff(self, mock_post, mock_sleep):
        import requests as req
        mock_post.side_effect = [
            req.exceptions.ConnectionError("reset"),
            _mock_ok_response("ok"),
        ]
        result = _api_call("https://example.com/api", {"pid": "test", "ak": "old"})
        self.assertEqual(result, "ok")
        mock_sleep.assert_called_once_with(2)

    @patch("core.pailixiang.time.sleep")
    @patch("core.pailixiang.requests.post")
    def test_timeout_error_retries(self, mock_post, mock_sleep):
        import requests as req
        mock_post.side_effect = [
            req.exceptions.Timeout("timed out"),
            _mock_ok_response("ok"),
        ]
        result = _api_call("https://example.com/api", {"pid": "test", "ak": "old"})
        self.assertEqual(result, "ok")
        mock_sleep.assert_called()


class TestFetchCv(unittest.TestCase):
    @patch("core.pailixiang.requests.get")
    def test_extracts_cv_from_html(self, mock_get):
        import core.pailixiang as px
        px._CACHED_CV = None
        px._CACHED_APP_KEY = None
        mock_get.return_value = MagicMock(text='<script src="https://abms.pailixiang.com/2.1.37/js/index.abc.js">')
        with patch("core.pailixiang._fetch_app_key", return_value=FALLBACK_APP_KEY):
            cv = _fetch_cv()
        self.assertEqual(cv, "137")

    @patch("core.pailixiang.requests.get")
    def test_fallback_on_network_error(self, mock_get):
        import core.pailixiang as px
        import requests as req
        px._CACHED_CV = None
        px._CACHED_APP_KEY = None
        mock_get.side_effect = req.RequestException("fail")
        cv = _fetch_cv()
        self.assertEqual(cv, FALLBACK_CV)


class TestGetAppKey(unittest.TestCase):
    @patch("core.pailixiang.requests.get")
    def test_extracts_from_js(self, mock_get):
        import core.pailixiang as px
        px._CACHED_CV = None
        px._CACHED_APP_KEY = None
        mock_get.side_effect = [
            MagicMock(text='<script src="https://abms.pailixiang.com/2.1.37/js/index.abc.js">'),
            MagicMock(text='appKey:"1e3a58fb24de413c9873542fc5667a25",envType:0'),
        ]
        key = _get_app_key()
        self.assertEqual(key, "1e3a58fb24de413c9873542fc5667a25")

    @patch("core.pailixiang.requests.get")
    def test_fallback_if_js_missing_key(self, mock_get):
        import core.pailixiang as px
        px._CACHED_CV = None
        px._CACHED_APP_KEY = None
        mock_get.side_effect = [
            MagicMock(text='<script src="https://abms.pailixiang.com/2.1.37/js/index.abc.js">'),
            MagicMock(text='no key here'),
        ]
        key = _get_app_key()
        self.assertEqual(key, FALLBACK_APP_KEY)


class TestFetchSpaVersion(unittest.TestCase):
    def test_parses_version_from_html(self):
        import core.pailixiang as px
        with patch.object(px.requests, 'get') as mock_get:
            mock_get.return_value = MagicMock(text='<script defer="defer" src="https://abms.pailixiang.com/2.1.39/js/index.a1b2c3d4.js"></script>')
            cv, js_url = _fetch_spa_version()
        self.assertEqual(cv, "139")
        self.assertIn("2.1.39", js_url)

    def test_raises_site_change_error_when_no_match(self):
        import core.pailixiang as px
        with patch.object(px.requests, 'get') as mock_get:
            mock_get.return_value = MagicMock(text="<html><body>nothing</body></html>")
            with self.assertRaises(SiteChangeError):
                _fetch_spa_version()


class TestApiAggGetView(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_extracts_id_without_g_prefix(self, mock_post):
        mock_post.return_value = _mock_ok_response({"Entity": {"Title": "Test"}})
        _api_agg_get_view("g113328594")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "113328594")

    @patch("core.pailixiang.requests.post")
    def test_strips_multiple_g(self, mock_post):
        mock_post.return_value = _mock_ok_response({"Entity": {"Title": "Test"}})
        _api_agg_get_view("gg123")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "123")


class TestApiAlbumGetView(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_extracts_id_without_a_prefix(self, mock_post):
        mock_post.return_value = _mock_ok_response({"Entity": {"ID": "inner-id", "Title": "Album"}})
        _api_album_get_view("a12096096366")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "12096096366")


class TestApiAlbumSearchPhoto(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_default_pagination(self, mock_post):
        mock_post.return_value = _mock_ok_response([])
        _api_album_search_photo("album-123")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["StartIndex"], 1)
        self.assertEqual(payload["SearchCount"], PAGE_SIZE)
        self.assertEqual(payload["AlbumID"], "album-123")


class TestFetchAllPhotos(unittest.TestCase):
    @patch("core.pailixiang._api_album_search_photo")
    def test_single_page(self, mock_search):
        mock_search.return_value = [{"Name": "img1.jpg"}, {"Name": "img2.jpg"}]
        result = _fetch_all_photos("album-1")
        self.assertEqual(len(result), 2)
        mock_search.assert_called_once()

    @patch("core.pailixiang._api_album_search_photo")
    def test_multi_page(self, mock_search):
        page1 = [{"Name": f"img{i}.jpg"} for i in range(PAGE_SIZE)]
        page2 = [{"Name": f"img{i}.jpg"} for i in range(30)]
        mock_search.side_effect = [page1, page2]
        result = _fetch_all_photos("album-1")
        self.assertEqual(len(result), PAGE_SIZE + 30)
        self.assertEqual(mock_search.call_count, 2)

    @patch("core.pailixiang._api_album_search_photo")
    def test_empty_album(self, mock_search):
        mock_search.return_value = []
        result = _fetch_all_photos("album-1")
        self.assertEqual(result, [])

    @patch("core.pailixiang._api_album_search_photo")
    def test_stops_on_api_error(self, mock_search):
        page1 = [{"Name": f"img{i}.jpg"} for i in range(PAGE_SIZE)]
        mock_search.side_effect = [page1, ApiError(8, "非法请求")]
        result = _fetch_all_photos("album-1")
        self.assertEqual(len(result), PAGE_SIZE)


class TestDownloadAggAlbums(unittest.TestCase):
    @patch("core.pailixiang._download_album_by_code")
    @patch("core.pailixiang._api_agg_get_view")
    def test_extracts_g_code(self, mock_agg, mock_dl):
        mock_agg.return_value = {
            "Entity": {"Title": "Event"},
            "ModuleList": [{"ItemList": [{"AlbumCode": "a123", "Name": "Sub", "PhotoQty": 5}]}],
        }
        download_agg_albums("https://live.pailixiang.com/album/main/g113328594", "/tmp/test")
        mock_agg.assert_called_once_with("113328594")
        mock_dl.assert_called_once()

    @patch("core.pailixiang._api_agg_get_view")
    def test_api_error_returns_gracefully(self, mock_agg):
        mock_agg.side_effect = ApiError(8, "非法请求")
        result = download_agg_albums("https://live.pailixiang.com/album/main/g113328594", "/tmp/test")
        self.assertIsNone(result)

    def test_invalid_url(self):
        result = download_agg_albums("https://example.com/no-code", "/tmp/test")
        self.assertIsNone(result)


class TestSanitizeDirname(unittest.TestCase):
    def test_strips_windows_reserved_chars(self):
        from core.pailixiang import _sanitize_dirname
        self.assertEqual(_sanitize_dirname('a/b\\c:d*e?f"g<h>i|j'), 'a b c d e f g h i j')

    def test_strips_newlines_and_control_chars(self):
        from core.pailixiang import _sanitize_dirname
        # Reproduces the WinError 123 path from issue report (embedded \n in album Name)
        name = "葡語國家/地區保險監管專員協會監管人員培訓研討會\nCONFERÊNCIA\n中國澳門 Macau, China"
        cleaned = _sanitize_dirname(name)
        self.assertNotIn("\n", cleaned)
        self.assertNotIn("/", cleaned)
        self.assertFalse(cleaned.startswith(" ") or cleaned.endswith(" "))

    def test_strips_trailing_dot(self):
        from core.pailixiang import _sanitize_dirname
        self.assertEqual(_sanitize_dirname("album."), "album")
        self.assertEqual(_sanitize_dirname("album1. ."), "album1")
        self.assertEqual(_sanitize_dirname("ends . "), "ends")

    def test_collapses_whitespace(self):
        from core.pailixiang import _sanitize_dirname
        self.assertEqual(_sanitize_dirname("a   b\t\tc"), "a b c")

    def test_truncates(self):
        from core.pailixiang import _sanitize_dirname
        long_name = "x" * 200
        self.assertEqual(len(_sanitize_dirname(long_name, max_len=50)), 50)

    def test_handles_br_tag_fallback(self):
        # Aggregation caller strips <br /> to " " before sanitizing (pailixiang.py line 340);
        # the sanitizer itself strips < > as Windows reserved chars — verify the post-strip input works.
        from core.pailixiang import _sanitize_dirname
        self.assertEqual(_sanitize_dirname("Title Subtitle"), "Title Subtitle")
        # Any residual <br /> in input has its <, >, and / chars replaced with space.
        self.assertEqual(_sanitize_dirname("Title<br />Subtitle"), "Title br Subtitle")


class TestResolvePhotoUrl(unittest.TestCase):
    def test_pass_through_when_downloadImageUrl_is_real_http_url(self):
        from core.pailixiang import _resolve_photo_url
        photo = {"DownloadImageUrl": "https://cdn.example.com/full.jpg",
                 "BigImageUrl": "https://cdn.example.com/big.jpg",
                 "ImageUrl": "https://cdn.example.com/small.jpg"}
        self.assertEqual(_resolve_photo_url(photo), "https://cdn.example.com/full.jpg")

    @patch("core.pailixiang._api_album_get_download_url")
    def test_calls_transfer_endpoint_for_pipe_format_downloadUrl(self, mock_transfer):
        from core.pailixiang import _resolve_photo_url
        # Pipe-form DownloadImageUrl is exchanged via /WapAbm/GetPhotoDownloadUrl.
        mock_transfer.return_value = "https://img1.pailixiang.com/trans/2606/688694296140802.jpg?Signature=abc"
        photo = {"DownloadImageUrl": "688694296140802|f61b6731-60b0-4947-8def-deef36201220|.jpg|0",
                 "Name": "NG1_0466.JPG",
                 "FileName": "28990655.jpg",
                 "BigImageUrl": "https://thumbnail0.baidupcs.com/thumbnail/abc?size=c1600_u1600"}
        self.assertEqual(_resolve_photo_url(photo),
                         "https://img1.pailixiang.com/trans/2606/688694296140802.jpg?Signature=abc")
        mock_transfer.assert_called_once_with(
            param="688694296140802|f61b6731-60b0-4947-8def-deef36201220|.jpg|0",
            origi_name="NG1_0466.JPG",
            file_name="28990655.jpg",
        )

    @patch("core.pailixiang._api_album_get_download_url")
    def test_falls_back_to_bigImageUrl_when_transfer_endpoint_fails(self, mock_transfer):
        from core.pailixiang import _resolve_photo_url
        # Restricted/paywalled albums reject the transfer request — fall back to preview.
        mock_transfer.side_effect = ApiError(8, "需要付费下载")
        photo = {"DownloadImageUrl": "688694296140802|f61b6731-60b0-4947-8def-deef36201220|.jpg|0",
                 "Name": "NG1_0466.JPG",
                 "FileName": "28990655.jpg",
                 "BigImageUrl": "https://thumbnail0.baidupcs.com/thumbnail/abc?size=c1600_u1600",
                 "ImageUrl": "https://thumbnail0.baidupcs.com/thumbnail/abc?size=c750_u1125"}
        self.assertEqual(_resolve_photo_url(photo),
                         "https://thumbnail0.baidupcs.com/thumbnail/abc?size=c1600_u1600")

    @patch("core.pailixiang._api_album_get_download_url")
    def test_falls_back_to_imageUrl_when_bigImageUrl_missing(self, mock_transfer):
        from core.pailixiang import _resolve_photo_url
        mock_transfer.side_effect = ApiError(8, "denied")
        photo = {"DownloadImageUrl": "garbage|not-a-real-url",
                 "Name": "x.jpg",
                 "FileName": "x.jpg",
                 "BigImageUrl": None,
                 "ImageUrl": "https://cdn.example.com/small.jpg"}
        self.assertEqual(_resolve_photo_url(photo), "https://cdn.example.com/small.jpg")

    def test_returns_empty_when_no_valid_url_and_no_pipe_form(self):
        from core.pailixiang import _resolve_photo_url
        self.assertEqual(_resolve_photo_url({}), "")
        self.assertEqual(_resolve_photo_url({"DownloadImageUrl": "garbage-no-pipe", "BigImageUrl": ""}), "")


class TestApiAlbumGetDownloadUrl(unittest.TestCase):
    @patch("core.pailixiang._api_call")
    @patch("core.pailixiang._build_payload")
    def test_calls_get_photo_download_url_endpoint(self, mock_build, mock_call):
        from core.pailixiang import _api_album_get_download_url, API_BASE
        mock_build.return_value = {"pid": "albumview", "Param": "p", "OrigiName": "n", "FileName": "f"}
        mock_call.return_value = "https://img1.pailixiang.com/trans/2606/x.jpg?Signature=y"
        result = _api_album_get_download_url(param="p", origi_name="n", file_name="f")
        self.assertEqual(result, "https://img1.pailixiang.com/trans/2606/x.jpg?Signature=y")
        mock_build.assert_called_once_with(
            pid="albumview", Param="p", OrigiName="n", FileName="f"
        )
        mock_call.assert_called_once_with(f"{API_BASE}/WapAbm/GetPhotoDownloadUrl",
                                          {"pid": "albumview", "Param": "p", "OrigiName": "n", "FileName": "f"})


class TestDownloadSingleAlbum(unittest.TestCase):
    @patch("core.pailixiang._download_album_by_code")
    def test_extracts_a_code(self, mock_dl):
        download_single_album("https://live.pailixiang.com/album/a12096096366", "/tmp/test")
        mock_dl.assert_called_once_with("a12096096366", "/tmp/test")

    def test_invalid_url(self):
        result = download_single_album("https://example.com/no-code", "/tmp/test")
        self.assertIsNone(result)


class TestUrlParsingRegex(unittest.TestCase):
    def test_g_code_patterns(self):
        self.assertIsNotNone(re.search(r"/g\d+", "/album/main/g113328594"))
        self.assertIsNotNone(re.search(r"/g\d+", "/album/main/g1"))
        self.assertIsNone(re.search(r"/g\d+", "/album/a123"))

    def test_a_code_patterns(self):
        self.assertIsNotNone(re.search(r"/a\d+", "/album/a12096096366"))
        self.assertIsNone(re.search(r"/a\d+", "/album/main/g113328594"))

    def test_no_false_match_album_in_path(self):
        self.assertIsNone(re.search(r"/g\d+", "/album/a12096096366"))
        self.assertIsNone(re.search(r"/a\d+", "/album/main/g113328594"))


if __name__ == "__main__":
    unittest.main()

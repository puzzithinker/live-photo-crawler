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
    _fetch_all_photos,
    download_agg_albums,
    download_single_album,
    APP_KEY,
    PAGE_SIZE,
)


class TestGenerateAk(unittest.TestCase):
    def test_length(self):
        ak = _generate_ak()
        self.assertEqual(len(ak), 3 + len(APP_KEY))

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
        base = list(APP_KEY)
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
    def test_network_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.RequestException("timeout")
        result = _download_image("https://example.com/img.jpg", "/tmp/nonexistent.jpg")
        self.assertFalse(result)


class TestApiAggGetView(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_extracts_id_without_g_prefix(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Data": {"Entity": {"Title": "Test"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        _api_agg_get_view("g113328594")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "113328594")

    @patch("core.pailixiang.requests.post")
    def test_strips_multiple_g(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Data": {"Entity": {"Title": "Test"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        _api_agg_get_view("gg123")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "123")


class TestApiAlbumGetView(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_extracts_id_without_a_prefix(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Data": {"Entity": {"ID": "inner-id", "Title": "Album"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        _api_album_get_view("a12096096366")
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        self.assertEqual(payload["ID"], "12096096366")


class TestApiAlbumSearchPhoto(unittest.TestCase):
    @patch("core.pailixiang.requests.post")
    def test_default_pagination(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

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

    def test_invalid_url(self):
        result = download_agg_albums("https://example.com/no-code", "/tmp/test")
        self.assertIsNone(result)


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

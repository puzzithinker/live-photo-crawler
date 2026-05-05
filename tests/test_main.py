import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from main import live_pailixiang_init, photoplus_init, pailixiang_init


class TestLivePailixiangRouting(unittest.TestCase):
    @patch("main.download_agg_albums")
    def test_g_url_routes_to_agg(self, mock_agg):
        live_pailixiang_init("https://live.pailixiang.com/album/main/g113328594", "/tmp/test")
        mock_agg.assert_called_once_with("https://live.pailixiang.com/album/main/g113328594", "/tmp/test")

    @patch("main.download_single_album")
    def test_a_url_routes_to_single(self, mock_single):
        live_pailixiang_init("https://live.pailixiang.com/album/a12096096366", "/tmp/test")
        mock_single.assert_called_once_with("https://live.pailixiang.com/album/a12096096366", "/tmp/test")

    @patch("main.download_agg_albums")
    @patch("main.download_single_album")
    def test_unknown_path_no_route(self, mock_single, mock_agg):
        live_pailixiang_init("https://live.pailixiang.com/unknown/path", "/tmp/test")
        mock_agg.assert_not_called()
        mock_single.assert_not_called()

    @patch("main.download_agg_albums")
    def test_strips_query_params(self, mock_agg):
        live_pailixiang_init("https://live.pailixiang.com/album/main/g123?ag=xxx", "/tmp/test")
        mock_agg.assert_called_once_with("https://live.pailixiang.com/album/main/g123", "/tmp/test")


class TestDomainRouting(unittest.TestCase):
    def test_live_pailixiang_hostname(self):
        self.assertEqual(urlparse("https://live.pailixiang.com/album/main/g123").hostname, "live.pailixiang.com")

    def test_www_pailixiang_hostname(self):
        self.assertEqual(urlparse("https://www.pailixiang.com/Album/Albums?id=123").hostname, "www.pailixiang.com")

    def test_photoplus_hostname(self):
        self.assertEqual(urlparse("https://live.photoplus.cn/live/123").hostname, "live.photoplus.cn")


class TestPhotoplusInit(unittest.TestCase):
    @patch("main.photoplus_dl")
    def test_delegates(self, mock_dl):
        photoplus_init(123, "/tmp/test")
        mock_dl.assert_called_once_with(123, "/tmp/test")


class TestPailixiangInit(unittest.TestCase):
    @patch("main.pailixiang_dl")
    def test_strips_query(self, mock_dl):
        pailixiang_init("https://www.pailixiang.com/Album?id=123&foo=bar", "/tmp/test")
        mock_dl.assert_called_once_with("https://www.pailixiang.com/Album", "/tmp/test")


if __name__ == "__main__":
    unittest.main()

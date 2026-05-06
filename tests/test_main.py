import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from main import dispatch_url, live_pailixiang_init, photoplus_init, pailixiang_init, build_parser


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


class TestDispatchUrl(unittest.TestCase):
    @patch("main.live_pailixiang_init")
    def test_dispatches_live_pailixiang(self, mock_init):
        dispatch_url("https://live.pailixiang.com/album/main/g123", "/tmp/test")
        mock_init.assert_called_once()

    @patch("main.pailixiang_init")
    def test_dispatches_www_pailixiang(self, mock_init):
        dispatch_url("https://www.pailixiang.com/Album?id=123", "/tmp/test")
        mock_init.assert_called_once()

    @patch("main.photoplus_init")
    def test_dispatches_photoplus(self, mock_init):
        dispatch_url("https://live.photoplus.cn/live/12345", "/tmp/test")
        mock_init.assert_called_once()

    def test_unsupported_domain_prints_error(self):
        with patch("builtins.print") as mock_print:
            dispatch_url("https://example.com/whatever", "/tmp/test")
            mock_print.assert_any_call("不支援的域名: example.com")

    def test_empty_url_ignored(self):
        with patch("builtins.print") as mock_print:
            dispatch_url("", "/tmp/test")
            mock_print.assert_not_called()


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


class TestArgparse(unittest.TestCase):
    def test_positional_url(self):
        parser = build_parser()
        args = parser.parse_args(["https://live.pailixiang.com/album/main/g123"])
        self.assertEqual(args.urls, ["https://live.pailixiang.com/album/main/g123"])
        self.assertEqual(args.output, "./res")

    def test_multiple_urls(self):
        parser = build_parser()
        args = parser.parse_args([
            "https://live.pailixiang.com/album/main/g123",
            "https://live.pailixiang.com/album/a456",
        ])
        self.assertEqual(len(args.urls), 2)

    def test_output_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-o", "/tmp/photos", "https://example.com"])
        self.assertEqual(args.output, "/tmp/photos")

    def test_file_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-f", "urls.txt"])
        self.assertEqual(args.file, "urls.txt")

    def test_no_urls_defaults_empty(self):
        parser = build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.urls, [])


if __name__ == "__main__":
    unittest.main()

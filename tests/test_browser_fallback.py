from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from douyin_analyzer.browser_fallback import (
    BrowserFallbackResolver,
    aweme_to_video_item,
    extract_aweme_records,
)


AWEME = {
    "aweme_id": "7604129988555574538",
    "desc": "这是一个公开视频 #知识分享",
    "duration": 45678,
    "author": {"nickname": "示例博主"},
    "text_extra": [{"hashtag_name": "知识分享"}],
    "video": {
        "play_addr": {
            "url_list": [
                "https://example-cdn.invalid/media-one.mp4",
                "https://example-cdn.invalid/media-two.mp4",
            ]
        }
    },
}


class BrowserFallbackParsingTests(unittest.TestCase):
    def test_extracts_aweme_from_nested_response(self) -> None:
        payload = {"status_code": 0, "data": {"aweme_list": [AWEME]}}
        records = list(extract_aweme_records(payload))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["aweme_id"], AWEME["aweme_id"])

    def test_converts_aweme_to_pipeline_item(self) -> None:
        item = aweme_to_video_item(AWEME)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.item_id, AWEME["aweme_id"])
        self.assertAlmostEqual(item.duration or 0, 45.678)
        self.assertEqual(item.uploader, "示例博主")
        self.assertIn("知识分享", item.hashtags)
        self.assertEqual(len(item.raw_info["direct_media_urls"]), 2)

    def test_cookie_file_keeps_only_douyin_domains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resolver = BrowserFallbackResolver(root / "profile", root / "temp")
            (root / "temp").mkdir(parents=True)
            target = resolver._write_cookie_file(
                [
                    {
                        "domain": ".douyin.com",
                        "path": "/",
                        "secure": True,
                        "expires": 2_000_000_000,
                        "name": "ttwid",
                        "value": "abc123",
                    },
                    {
                        "domain": ".notdouyin.com",
                        "path": "/",
                        "secure": True,
                        "expires": 2_000_000_000,
                        "name": "unrelated",
                        "value": "secret",
                    },
                ]
            )
            content = target.read_text(encoding="utf-8")
            self.assertIn("ttwid", content)
            self.assertNotIn("unrelated", content)
            resolver.cleanup()
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

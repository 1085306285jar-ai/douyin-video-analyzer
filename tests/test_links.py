from __future__ import annotations

import unittest

from douyin_analyzer.domain import LinkType
from douyin_analyzer.exceptions import InvalidLinkError, UnsupportedLinkError
from douyin_analyzer.links import detect_link_type, extract_url, parse_link


class LinkParsingTests(unittest.TestCase):
    def test_extracts_url_from_share_copy(self) -> None:
        text = "复制打开抖音，看看【示例】 https://v.douyin.com/AbC123/ 03/21"
        self.assertEqual(extract_url(text), "https://v.douyin.com/AbC123/")

    def test_strips_chinese_trailing_punctuation(self) -> None:
        text = "看看这个：https://www.douyin.com/video/123456789。"
        self.assertEqual(extract_url(text), "https://www.douyin.com/video/123456789")

    def test_detects_three_direct_link_types(self) -> None:
        self.assertEqual(
            detect_link_type("https://www.douyin.com/video/123456789"),
            LinkType.SINGLE,
        )
        self.assertEqual(
            detect_link_type("https://www.douyin.com/collection/123456789"),
            LinkType.COLLECTION,
        )
        self.assertEqual(
            detect_link_type("https://www.douyin.com/user/MS4wLjABAAAA"),
            LinkType.AUTHOR,
        )

    def test_short_link_stays_auto_until_extractor_resolves_redirect(self) -> None:
        parsed = parse_link("https://v.douyin.com/AbC123/")
        self.assertEqual(parsed.link_type, LinkType.AUTO)

    def test_manual_mode_overrides_detection(self) -> None:
        parsed = parse_link(
            "https://www.douyin.com/user/MS4wLjABAAAA", LinkType.AUTHOR
        )
        self.assertEqual(parsed.link_type, LinkType.AUTHOR)

    def test_rejects_missing_and_non_douyin_links(self) -> None:
        with self.assertRaises(InvalidLinkError):
            parse_link("没有链接")
        with self.assertRaises(UnsupportedLinkError):
            parse_link("https://example.com/video/123")

    def test_rejects_lookalike_domain(self) -> None:
        with self.assertRaises(UnsupportedLinkError):
            parse_link("https://douyin.com.example.org/video/123")


if __name__ == "__main__":
    unittest.main()

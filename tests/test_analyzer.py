from __future__ import annotations

import unittest

from douyin_analyzer.analyzer import LocalContentAnalyzer, normalize_transcript
from douyin_analyzer.exceptions import NoSpeechError


SAMPLE = (
    "很多人做短视频只盯着播放量，其实真正决定成交的是人群是否准确。"
    "第一步先确定一个具体用户，第二步围绕他的真实问题持续输出。"
    "记住，不是内容越多越好，而是每条内容都要解决一个明确问题。"
    "只要选题精准，哪怕粉丝不多，也能获得稳定咨询。"
)


class LocalAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = LocalContentAnalyzer()

    def test_produces_required_five_sections(self) -> None:
        report = self.analyzer.analyze(
            SAMPLE,
            title="短视频获客的三个关键 #短视频运营",
            source_hashtags=["内容创业"],
        )
        self.assertTrue(report.topic)
        self.assertGreaterEqual(len(report.core_points), 2)
        self.assertLessEqual(len(report.core_points), 5)
        self.assertTrue(report.highlights)
        self.assertEqual(len(report.tags), 5)
        self.assertTrue(all(tag.startswith("#") for tag in report.tags))
        self.assertIn(report.emotion, {"干货/科普", "产品测评", "带货推荐", "吐槽评论", "情感鸡汤", "日常分享"})

    def test_highlights_are_verbatim_not_invented(self) -> None:
        report = self.analyzer.analyze(SAMPLE)
        for highlight in report.highlights:
            self.assertIn(highlight, SAMPLE)

    def test_classifies_product_review(self) -> None:
        text = "今天实测两款耳机。我们对比续航、参数和佩戴体验。第一款优点是轻，第二款缺点是延迟高。最后给出购买建议。"
        report = self.analyzer.analyze(text, title="两款耳机对比测评")
        self.assertEqual(report.emotion, "产品测评")

    def test_rejects_too_short_or_empty_transcript(self) -> None:
        with self.assertRaises(NoSpeechError):
            self.analyzer.analyze("")
        with self.assertRaises(NoSpeechError):
            self.analyzer.analyze("嗯，好。")

    def test_normalizes_whitespace_and_duplicate_punctuation(self) -> None:
        self.assertEqual(normalize_transcript(" 你好   世界！！\n 下一句。 "), "你好 世界！\n下一句。")


if __name__ == "__main__":
    unittest.main()

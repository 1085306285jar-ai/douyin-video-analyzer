from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .domain import AnalysisReport
from .exceptions import NoSpeechError


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|[\r\n]+")
ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{1,24}")
CHINESE_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
HASHTAG_RE = re.compile(r"#([\w\u4e00-\u9fff-]{2,24})")

FILLER_PHRASES = {
    "然后",
    "就是",
    "这个",
    "那个",
    "一个",
    "我们",
    "你们",
    "他们",
    "大家",
    "可以",
    "觉得",
    "其实",
    "因为",
    "所以",
    "如果",
    "但是",
    "还是",
    "真的",
    "非常",
    "可能",
    "应该",
    "什么",
    "怎么",
    "这样",
    "这种",
    "没有",
    "不是",
    "今天",
    "现在",
    "时候",
    "一下",
    "这里",
    "来说",
    "进行",
    "已经",
    "知道",
    "东西",
    "问题",
}

STOP_CHARS = set("的了是在和有就都而及与着或把被也很到让给从对这那你我他她它们啊呢吧吗呀哦哈会能要说看做用来去上下一些一种个中为")

EMOTION_RULES: dict[str, tuple[str, ...]] = {
    "产品测评": (
        "测评",
        "实测",
        "对比",
        "参数",
        "体验",
        "优点",
        "缺点",
        "开箱",
    ),
    "带货推荐": (
        "下单",
        "购买",
        "链接",
        "性价比",
        "入手",
        "推荐",
        "优惠",
        "价格",
        "直播间",
    ),
    "吐槽评论": (
        "吐槽",
        "离谱",
        "无语",
        "坑人",
        "踩坑",
        "太差",
        "别信",
        "曝光",
    ),
    "情感鸡汤": (
        "人生",
        "成长",
        "感悟",
        "治愈",
        "情绪",
        "努力",
        "坚持",
        "内心",
    ),
    "干货/科普": (
        "方法",
        "步骤",
        "原理",
        "知识",
        "技巧",
        "教程",
        "首先",
        "其次",
        "注意",
        "为什么",
    ),
    "日常分享": (
        "今天",
        "日常",
        "生活",
        "分享",
        "记录",
        "朋友",
        "回家",
        "孩子",
    ),
}

CATEGORY_TAGS: dict[str, tuple[str, ...]] = {
    "产品测评": ("产品测评", "真实体验", "避坑指南"),
    "带货推荐": ("好物分享", "购物攻略", "性价比"),
    "吐槽评论": ("热点讨论", "真实观点", "避坑"),
    "情感鸡汤": ("人生感悟", "情绪价值", "自我成长"),
    "干货/科普": ("知识分享", "实用干货", "学习"),
    "日常分享": ("生活记录", "日常分享", "真实生活"),
}

HIGHLIGHT_MARKERS = (
    "记住",
    "一定",
    "千万",
    "本质",
    "真正",
    "最重要",
    "关键",
    "不要",
    "不是",
    "只有",
    "为什么",
    "结论",
    "核心",
)


def normalize_transcript(text: str) -> str:
    text = (text or "").replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"([。！？!?；;，,])\1+", r"\1", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    pieces = [piece.strip(" ，,\t") for piece in SENTENCE_SPLIT_RE.split(text)]
    sentences = [piece for piece in pieces if len(_semantic_chars(piece)) >= 4]
    if len(sentences) >= 2:
        return sentences

    clauses = [
        piece.strip()
        for piece in re.split(r"[，,：:]", text)
        if len(_semantic_chars(piece)) >= 6
    ]
    return clauses or sentences


def _semantic_chars(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]", "", text)


def _similarity_tokens(sentence: str) -> Counter[str]:
    tokens: list[str] = [word.lower() for word in ASCII_WORD_RE.findall(sentence)]
    for chunk in CHINESE_CHUNK_RE.findall(sentence):
        if len(chunk) == 2:
            tokens.append(chunk)
        else:
            tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return Counter(token for token in tokens if token not in FILLER_PHRASES)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = left.keys() & right.keys()
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _rank_sentences(sentences: list[str]) -> list[tuple[int, float]]:
    count = len(sentences)
    if count == 1:
        return [(0, 1.0)]

    vectors = [_similarity_tokens(sentence) for sentence in sentences]
    graph = [[0.0] * count for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            score = _cosine(vectors[left], vectors[right])
            graph[left][right] = score
            graph[right][left] = score

    ranks = [1.0 / count] * count
    damping = 0.85
    for _ in range(30):
        next_ranks: list[float] = []
        for target in range(count):
            incoming = 0.0
            for source in range(count):
                total = sum(graph[source])
                if total > 0:
                    incoming += graph[source][target] / total * ranks[source]
            next_ranks.append((1.0 - damping) / count + damping * incoming)
        if max(abs(a - b) for a, b in zip(ranks, next_ranks)) < 1e-6:
            ranks = next_ranks
            break
        ranks = next_ranks

    scored: list[tuple[int, float]] = []
    for index, (sentence, rank) in enumerate(zip(sentences, ranks)):
        length = len(_semantic_chars(sentence))
        length_factor = 1.0 if 12 <= length <= 80 else 0.78
        position_bonus = 0.10 if index == 0 else (0.05 if index == count - 1 else 0.0)
        signal_bonus = min(0.14, 0.025 * sum(marker in sentence for marker in HIGHLIGHT_MARKERS))
        scored.append((index, rank * length_factor + position_bonus + signal_bonus))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _near_duplicate(left: str, right: str) -> bool:
    left_tokens = set(_similarity_tokens(left))
    right_tokens = set(_similarity_tokens(right))
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.72


def _clean_title(title: str) -> str:
    title = HASHTAG_RE.sub("", title or "")
    title = re.sub(r"[@｜|].*$", "", title).strip(" -—_，,。")
    return title


def _truncate(text: str, limit: int = 56) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip("，,。；; ") + "……"


def _classify_emotion(text: str) -> str:
    scores: dict[str, float] = {}
    for category, words in EMOTION_RULES.items():
        scores[category] = sum(text.count(word) for word in words)

    top_category = max(scores, key=scores.get)
    if scores[top_category] == 0:
        if re.search(r"(?:第一|第二|首先|其次|步骤|方法|注意)", text):
            return "干货/科普"
        return "日常分享"
    return top_category


def _candidate_keywords(text: str, title: str, existing: list[str]) -> list[str]:
    scores: Counter[str] = Counter()
    corpus = f"{title}。{text}"

    for word in ASCII_WORD_RE.findall(corpus):
        lowered = word.lower()
        if len(lowered) >= 2:
            scores[word] += 3 if word in title else 1

    for chunk in CHINESE_CHUNK_RE.findall(corpus):
        if len(chunk) > 20:
            chunk = chunk[:20]
        for size in (4, 3, 2):
            if len(chunk) < size:
                continue
            for index in range(len(chunk) - size + 1):
                phrase = chunk[index : index + size]
                if phrase in FILLER_PHRASES:
                    continue
                if phrase[0] in STOP_CHARS or phrase[-1] in STOP_CHARS:
                    continue
                if any(filler in phrase for filler in FILLER_PHRASES if len(filler) == 2):
                    continue
                scores[phrase] += size + (3 if phrase in title else 0)

    normalized_existing = {tag.lower().lstrip("#") for tag in existing}
    selected: list[str] = []
    for phrase, _ in scores.most_common(80):
        key = phrase.lower().lstrip("#")
        if key in normalized_existing:
            continue
        if any(key in old.lower() or old.lower() in key for old in selected):
            continue
        selected.append(phrase)
        if len(selected) >= 8:
            break
    return selected


@dataclass(slots=True)
class LocalContentAnalyzer:
    min_text_chars: int = 8

    def analyze(
        self,
        text: str,
        *,
        title: str = "",
        source_hashtags: list[str] | None = None,
    ) -> AnalysisReport:
        transcript = normalize_transcript(text)
        if len(_semantic_chars(transcript)) < self.min_text_chars:
            raise NoSpeechError()

        sentences = split_sentences(transcript)
        if not sentences:
            raise NoSpeechError()
        ranking = _rank_sentences(sentences)

        desired_points = min(5, max(2, math.ceil(len(sentences) / 3)))
        selected_indices: list[int] = []
        for index, _score in ranking:
            if any(_near_duplicate(sentences[index], sentences[old]) for old in selected_indices):
                continue
            selected_indices.append(index)
            if len(selected_indices) >= desired_points:
                break
        if len(selected_indices) < min(2, len(sentences)):
            for index in range(len(sentences)):
                if index not in selected_indices:
                    selected_indices.append(index)
                if len(selected_indices) >= min(2, len(sentences)):
                    break
        core_points = [_truncate(sentences[index], 100) for index in sorted(selected_indices)]

        clean_title = _clean_title(title)
        topic_source = clean_title if len(_semantic_chars(clean_title)) >= 5 else sentences[ranking[0][0]]
        topic = _truncate(topic_source, 58)

        highlight_scores: list[tuple[int, float]] = []
        for index, sentence in enumerate(sentences):
            length = len(_semantic_chars(sentence))
            if not 8 <= length <= 100:
                continue
            score = 0.0
            score += 1.8 * sum(marker in sentence for marker in HIGHLIGHT_MARKERS)
            score += 0.8 if re.search(r"\d|一|二|三|四|五", sentence) else 0.0
            score += 1.2 if re.search(r"不是.+而是|只要.+就|只有.+才|越.+越", sentence) else 0.0
            score += 0.4 if sentence.endswith(("。", "！", "!")) else 0.0
            score += ranking.index(next(item for item in ranking if item[0] == index)) < max(2, len(ranking) // 3)
            highlight_scores.append((index, score))
        highlight_scores.sort(key=lambda item: item[1], reverse=True)
        highlights: list[str] = []
        for index, _score in highlight_scores:
            candidate = sentences[index].strip()
            if any(_near_duplicate(candidate, old) for old in highlights):
                continue
            highlights.append(candidate)
            if len(highlights) >= min(3, max(1, len(sentences) // 4)):
                break

        emotion = _classify_emotion(transcript)
        source_tags = [tag.strip().lstrip("#") for tag in (source_hashtags or []) if tag.strip()]
        source_tags.extend(match.group(1) for match in HASHTAG_RE.finditer(title or ""))
        candidate_tags = _candidate_keywords(transcript, title, source_tags)
        # Preserve room for stable category tags. Pure n-gram ranking can otherwise
        # fill all five slots with overlapping fragments from a short title.
        keyword_slots = max(1, 3 - min(2, len(source_tags)))
        candidate_tags = candidate_tags[:keyword_slots]
        fallback_tags = list(CATEGORY_TAGS[emotion]) + ["抖音创作", "内容拆解"]

        tags: list[str] = []
        for candidate in source_tags + candidate_tags + fallback_tags:
            normalized = re.sub(r"\s+", "", candidate).strip("#，,。")
            if not normalized or len(normalized) > 24:
                continue
            if normalized.lower() in {tag.lstrip("#").lower() for tag in tags}:
                continue
            tags.append(f"#{normalized}")
            if len(tags) == 5:
                break

        return AnalysisReport(
            topic=topic,
            core_points=core_points,
            highlights=highlights,
            emotion=emotion,
            tags=tags,
            transcript=transcript,
        )

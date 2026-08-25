from __future__ import annotations

import re
from urllib.parse import urlparse

from .domain import LinkType, ParsedLink
from .exceptions import InvalidLinkError, UnsupportedLinkError


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = "，。！？；：、,.!?;:)]}）】》」』"


def _is_douyin_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return (
        host == "douyin.com"
        or host.endswith(".douyin.com")
        or host == "iesdouyin.com"
        or host.endswith(".iesdouyin.com")
    )


def extract_url(text: str) -> str:
    cleaned = (text or "").strip()
    match = URL_RE.search(cleaned)
    if not match:
        raise InvalidLinkError()
    return match.group(0).rstrip(TRAILING_PUNCTUATION)


def detect_link_type(url: str) -> LinkType:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = (parsed.hostname or "").lower()

    if host.startswith("v.") or host.startswith("s."):
        return LinkType.AUTO
    if re.search(r"/(?:video|note)/\d+", path):
        return LinkType.SINGLE
    if "/collection/" in path or "/mix/" in path:
        return LinkType.COLLECTION
    if "/user/" in path:
        return LinkType.AUTHOR
    return LinkType.AUTO


def parse_link(text: str, requested_mode: LinkType = LinkType.AUTO) -> ParsedLink:
    url = extract_url(text)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidLinkError()
    if not _is_douyin_host(parsed.hostname):
        raise UnsupportedLinkError()
    detected = detect_link_type(url)
    return ParsedLink(url=url, link_type=requested_mode if requested_mode != LinkType.AUTO else detected)

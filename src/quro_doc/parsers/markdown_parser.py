"""MarkdownMediaParser — extract embed media references from markdown via mistune.

Pure function. No regex for markdown pattern matching. No I/O. No quro-doc imports.
Wraps mistune (AST-based parser) to identify ![](url), [text](url), and <img src="url">
references with accurate positions in the source text.

TDA role: Kernel.
"""

from dataclasses import dataclass

import mistune


@dataclass
class MediaRef:
    """A media reference found in markdown content.

    Fields:
        start_pos:  Character offset where the reference starts in the source.
        end_pos:    Character offset where the reference ends (exclusive).
        url:        The referenced URL.
        alt:        Alt text (for images) or link text (for links).
        media_type: "image", "link", or "unknown".
    """

    start_pos: int
    end_pos: int
    url: str
    alt: str
    media_type: str  # "image" | "link" | "unknown"


class MarkdownMediaParser:
    """Parse markdown and extract embed media references. Wraps mistune.

    Pure function. No I/O. No quro-doc imports.
    TDA role: Kernel.
    """

    def extract(self, body: str) -> list[MediaRef]:
        """Extract media references from a markdown body string.

        Contract:
          1. Parses body via mistune AST.
          2. Returns MediaRef for every ![alt](url), <img src="url">, [text](url).
          3. Skips asset:// URLs (already rewritten).
          4. Returns empty list for input with no media.
          5. On parse error: returns partial results (best-effort), never raises.
          6. Result list is sorted by start_pos ascending.
        """
        try:
            tokens, _ = mistune.create_markdown(renderer=None).parse(body)
        except Exception:
            return []

        raw_refs: list[dict] = []
        self._collect_refs(tokens, raw_refs)

        refs: list[MediaRef] = []
        search_from = 0
        for raw in raw_refs:
            start, end = _find_ref_position(body, raw, search_from)
            if start >= 0:
                refs.append(
                    MediaRef(
                        start_pos=start,
                        end_pos=end,
                        url=raw["url"],
                        alt=raw["alt"],
                        media_type=raw["media_type"],
                    )
                )
                search_from = end

        refs.sort(key=lambda r: r.start_pos)
        return refs

    def _collect_refs(self, tokens: list[dict], result: list[dict]) -> None:
        """Walk mistune AST tokens depth-first and collect raw media reference info."""
        for token in tokens:
            ttype = token["type"]

            if ttype == "image":
                url = token["attrs"]["url"]
                if not url.startswith("asset://"):
                    result.append(
                        {
                            "url": url,
                            "alt": _extract_text(token),
                            "media_type": "image",
                            "raw": None,
                        }
                    )

            elif ttype == "link":
                url = token["attrs"]["url"]
                if not url.startswith("asset://") and _is_media_url(url):
                    result.append(
                        {
                            "url": url,
                            "alt": _extract_text(token),
                            "media_type": "link",
                            "raw": None,
                        }
                    )

            elif ttype in ("inline_html", "block_html"):
                raw = token["raw"].strip()
                if raw.startswith("<img"):
                    src = _extract_img_src(raw)
                    if src and not src.startswith("asset://"):
                        result.append(
                            {
                                "url": src,
                                "alt": _extract_img_alt(raw),
                                "media_type": "image",
                                "raw": token["raw"],
                            }
                        )

            if "children" in token:
                self._collect_refs(token["children"], result)


_MEDIA_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".ogg", ".webm", ".mkv",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".css", ".js",
})


def _is_media_url(url: str) -> bool:
    """Check if a URL points to a downloadable media/binary file.

    Only links to known media file types are considered assets.
    Regular hyperlinks (HTML pages, DOI links, etc.) are NOT assets.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in _MEDIA_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def _extract_text(token: dict) -> str:
    """Extract plain text content from a mistune token tree."""
    texts: list[str] = []

    def _walk(t: dict) -> None:
        if t["type"] == "text":
            texts.append(t["raw"])
        elif t["type"] in ("softbreak", "linebreak"):
            texts.append(" ")
        if "children" in t:
            for child in t["children"]:
                _walk(child)

    _walk(token)
    return "".join(texts)


def _extract_img_src(raw_html: str) -> str | None:
    """Extract src attribute value from an <img> HTML tag string."""
    lower = raw_html.lower()
    idx = lower.find("src=")
    if idx < 0:
        return None
    idx += 4
    quote = raw_html[idx]
    if quote in ('"', "'"):
        start = idx + 1
        end = raw_html.find(quote, start)
        if end < 0:
            return None
        return raw_html[start:end]
    else:
        start = idx
        end = raw_html.find(" ", start)
        if end < 0:
            end = raw_html.find(">", start)
        if end < 0:
            return None
        return raw_html[start:end].rstrip(">")


def _extract_img_alt(raw_html: str) -> str:
    """Extract alt attribute value from an <img> HTML tag string."""
    lower = raw_html.lower()
    idx = lower.find("alt=")
    if idx < 0:
        return ""
    idx += 4
    quote = raw_html[idx]
    if quote in ('"', "'"):
        start = idx + 1
        end = raw_html.find(quote, start)
        if end < 0:
            return ""
        return raw_html[start:end]
    return ""


def _find_ref_position(
    body: str, ref: dict, search_from: int
) -> tuple[int, int]:
    """Find (start_pos, end_pos) of a media reference in the body string.

    For HTML images, locates the exact raw HTML string.
    For markdown images/links, locates the bracket-delimited pattern
    by finding the URL and expanding to the enclosing brackets.
    Returns (-1, -1) if position cannot be determined.
    """
    raw_html = ref.get("raw")
    if raw_html is not None:
        pos = body.find(raw_html, search_from)
        if pos >= 0:
            return (pos, pos + len(raw_html))
        return (-1, -1)

    url = ref["url"]
    media_type = ref["media_type"]

    url_pos = body.find(url, search_from)
    if url_pos < 0:
        return (-1, -1)

    if media_type == "link":
        if _is_autolink(body, url_pos, len(url)):
            return (url_pos - 1, url_pos + len(url) + 1)
        open_pos = body.rfind("[", 0, url_pos)
    else:
        open_pos = body.rfind("![", 0, url_pos)

    if open_pos < 0:
        return (-1, -1)

    close_pos = body.find(")", url_pos + len(url))
    if close_pos < 0:
        return (-1, -1)

    return (open_pos, close_pos + 1)


def _is_autolink(body: str, url_pos: int, url_len: int) -> bool:
    """Check if a URL is inside an autolink <url> pattern."""
    if url_pos == 0 or url_pos + url_len >= len(body):
        return False
    return body[url_pos - 1] == "<" and body[url_pos + url_len] == ">"

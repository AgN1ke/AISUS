from __future__ import annotations

import html
import re
import urllib.parse

_FENCED_CODE_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+-]+)?\n?(?P<code>.*?)```",
    flags=re.S,
)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_MARKDOWN_LINK_RE = re.compile(
    r"\[((?:[^\[\]\n]|\[[^\]\n]*\])+)\]\((https?://[^\s)]+)\)"
)
_BOLD_DOUBLE_RE = re.compile(r"\*\*([^\n*][^*]*?)\*\*")
_BOLD_SINGLE_RE = re.compile(r"(?<!\*)\*([^\n*][^*]*?)\*(?!\*)")
_ITALIC_RE = re.compile(r"(?<!_)_([^\n_][^_]*?)_(?!_)")


def _normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return ""
    parsed = urllib.parse.urlparse(candidate)
    if not parsed.scheme:
        candidate = f"https://{candidate.lstrip('/')}"
        parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return candidate


def _source_label(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    domain = (parsed.netloc or url).lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or "джерело"


def format_source_links_markdown(sources: list[dict], limit: int = 5) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    for source in sources:
        url = _normalize_url(str(source.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        label = _source_label(url).replace("[", "(").replace("]", ")")
        lines.append(f"- [{label}]({url})")
        if len(lines) >= limit:
            break

    return "\n".join(lines)


def render_telegram_html(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""

    placeholders: dict[str, str] = {}

    def stash(value: str) -> str:
        token = f"@@TGHTML{len(placeholders)}@@"
        placeholders[token] = value
        return token

    def replace_fenced(match: re.Match[str]) -> str:
        code = (match.group("code") or "").strip("\n")
        return stash(f"<pre><code>{html.escape(code)}</code></pre>")

    def replace_inline(match: re.Match[str]) -> str:
        code = match.group(1) or ""
        return stash(f"<code>{html.escape(code)}</code>")

    def replace_link(match: re.Match[str]) -> str:
        label = html.escape((match.group(1) or "").strip())
        url = _normalize_url(match.group(2) or "")
        if not url:
            return html.escape(match.group(0))
        return stash(f'<a href="{html.escape(url, quote=True)}">{label}</a>')

    rendered = _FENCED_CODE_RE.sub(replace_fenced, raw)
    rendered = _MARKDOWN_LINK_RE.sub(replace_link, rendered)
    rendered = _INLINE_CODE_RE.sub(replace_inline, rendered)
    rendered = html.escape(rendered)
    rendered = _BOLD_DOUBLE_RE.sub(lambda m: f"<b>{m.group(1)}</b>", rendered)
    rendered = _BOLD_SINGLE_RE.sub(lambda m: f"<b>{m.group(1)}</b>", rendered)
    rendered = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1)}</i>", rendered)

    for token, value in placeholders.items():
        rendered = rendered.replace(token, value)

    return rendered

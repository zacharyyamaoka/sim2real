"""HTML helpers every catalog's pages use: escaping, tables, Markdown-lite, links, the breadcrumb and results line."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def host_of(url) -> str:
    host = urlparse(url).hostname if isinstance(url, str) else None
    return (host[4:] if host and host.startswith("www.") else host) or ""


def size_text(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB" if n >= 1e3 else f"{n:,} bytes"


def placeholder(text: str) -> str:
    """A page section that is not built yet says so, marked (the site never pretends): `text` is HTML."""
    return f'<p class="placeholder"><b>Placeholder</b> {text}</p>'


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else (words or word + 's')}"


def table(head: list[str], rows: list[list[str]], caption=None, attrs="") -> str:
    """A table (cells are already HTML) inside the scroll box that keeps a phone page from scrolling sideways."""
    cap = f"<caption>{caption}</caption>" if caption else ""
    head_html = "".join(f'<th scope="col">{cell}</th>' for cell in head)
    body = "\n".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table{attrs}>{cap}<thead><tr>{head_html}</tr></thead>\n<tbody>\n{body}\n</tbody></table></div>'


def code_block(text: str) -> str:
    return f"<pre><code>{html.escape(text, quote=False)}</code></pre>"


INLINE = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _table_cells(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [cell.strip().replace("\\|", "|") for cell in cells]


class Html:
    """The helpers that know the catalog's own origin: its absolute URLs are linked site-relative, so the pages also
    work on a local server. A catalog makes one and re-exports its bound methods under the old names."""

    def __init__(self, origin: str):
        self.origin = origin

    def site_href(self, url):
        """The catalog's own files are linked site-relative, so the pages also work on a local server."""
        if isinstance(url, str) and url.startswith(self.origin + "/"):
            return url[len(self.origin):]
        return url

    def link(self, url, text, title=None) -> str:
        """An <a> only for an http(s) URL, a site path or a #fragment of this page; anything else (or nothing) is shown
        as plain text. WHY the fragment: a record page's in-page lists (a part page's "Views of this part", its checks
        line, each comparison's record) are links to its own sections."""
        url = self.site_href(url)
        ok = isinstance(url, str) and (url.startswith(("https://", "http://")) or (url.startswith("/") and not url.startswith("//"))
                                       or (url.startswith("#") and len(url) > 1))
        if not ok:
            return e(text)
        extra = f' title="{e(title)}"' if title else ""
        return f'<a href="{e(url)}"{extra}>{e(text)}</a>'

    def inline_markdown(self, text: str) -> str:
        out, last = [], 0
        for match in INLINE.finditer(text):
            out.append(e(text[last:match.start()]))
            code, strong, label, url = match.groups()
            if code is not None:
                out.append(f"<code>{e(code)}</code>")
            elif strong is not None:
                out.append(f"<strong>{e(strong)}</strong>")
            elif url.startswith(("https://", "http://")):
                out.append(self.link(url, label))
            else:
                # WHY not a link: a path relative to the repository (../SCHEMA2.md) has no page on the site; keep it as words.
                out.append(f"{e(label)} (<code>{e(url)}</code>)")
            last = match.end()
        out.append(e(text[last:]))
        return "".join(out)

    def markdown_lite(self, text: str) -> str:
        """A record's notes or a guide as HTML: headings, paragraphs, bullet and numbered lists (one
        nested list deep), fenced code, pipe tables, quotes, `code`, **bold** and [links](https://…). Anything else stays as the
        literal text it is, escaped; nothing is dropped. Headings start at h3: the text sits under the page's own h2."""
        lines = text.splitlines()
        blocks, para = [], []

        def flush():
            if para:
                blocks.append("<p>" + self.inline_markdown(" ".join(para)) + "</p>")
                para.clear()

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                flush()
                fence, body = stripped[:3], []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(fence):
                    body.append(lines[i])
                    i += 1
                blocks.append(code_block("\n".join(body)))
                i += 1
                continue
            if not stripped:
                flush()
                i += 1
                continue
            heading = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
            if heading:
                flush()
                depth = min(6, len(heading.group(1)) + 2)
                blocks.append(f"<h{depth}>{self.inline_markdown(heading.group(2))}</h{depth}>")
                i += 1
                continue
            if stripped.startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]):
                flush()
                head = _table_cells(stripped)
                i += 2
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append([self.inline_markdown(cell) for cell in _table_cells(lines[i])])
                    i += 1
                blocks.append(table([self.inline_markdown(cell) for cell in head], rows))
                continue
            if stripped.startswith(">"):
                flush()
                quoted = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quoted.append(lines[i].strip()[1:].strip())
                    i += 1
                blocks.append(f"<blockquote>{self.markdown_lite(chr(10).join(quoted))}</blockquote>")
                continue
            item = LIST_ITEM.match(line)
            if item and not item.group(1):
                flush()
                ordered = item.group(2)[0].isdigit()
                start = int(item.group(2)[:-1]) if ordered else 1
                items = []  # [text, sub-items, sub-items are numbered]
                while i < len(lines):
                    current = LIST_ITEM.match(lines[i])
                    if current and not current.group(1):
                        if current.group(2)[0].isdigit() != ordered:
                            break
                        items.append([current.group(3), [], False])
                    elif current and items:
                        items[-1][1].append(current.group(3))
                        items[-1][2] = current.group(2)[0].isdigit()
                    elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                        if items[-1][1]:
                            items[-1][1][-1] += " " + lines[i].strip()
                        else:
                            items[-1][0] += " " + lines[i].strip()
                    else:
                        break
                    i += 1
                tag = "ol" if ordered else "ul"
                opening = f'<ol start="{start}">' if ordered and start != 1 else f"<{tag}>"
                rendered = []
                for words, subs, numbered in items:
                    sub_tag = "ol" if numbered else "ul"
                    nested = (f"<{sub_tag}>" + "".join(f"<li>{self.inline_markdown(sub)}</li>" for sub in subs) + f"</{sub_tag}>"
                              if subs else "")
                    rendered.append(f"<li>{self.inline_markdown(words)}{nested}</li>")
                blocks.append(opening + "".join(rendered) + f"</{tag}>")
                continue
            para.append(stripped)
            i += 1
        flush()
        return "\n".join(blocks)


def breadcrumb(items, back: list[str] | None = None) -> str:
    """The drill-down breadcrumb: items are (text, href); every crumb is a real link, the last one to this page.
    With `back` (the list URLs this page can be reached from), a "‹ Back to results" link that static/site.js shows only
    when the browser came here from one of them (document.referrer, same site): no tracking, nothing stored."""
    links = []
    for n, (text, href) in enumerate(items):
        current = ' aria-current="page"' if n == len(items) - 1 else ""
        links.append(f'<a href="{e(href)}"{current}>{e(text)}</a>' if href else e(text))
    back_link = (f'<a class="back" data-lists="{e(" ".join(back))}" hidden>‹ Back to results</a><span class="sep" hidden> · </span>'
                 if back else "")
    return f'<nav class="crumbs" aria-label="Breadcrumb">{back_link}{" › ".join(links)}</nav>'


def results_line(count_html: str, crumbs: str) -> str:
    """McMaster's line above results: "<count> | <breadcrumb>"."""
    return f'<div class="results"><strong id="shown" aria-live="polite">{count_html}</strong> <span class="sep">|</span> {crumbs}</div>'

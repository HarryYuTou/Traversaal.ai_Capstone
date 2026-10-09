"""Reference material from a web page, so a script can be grounded in a source the user names.

The page is downloaded once and reduced to its readable text: headings,
paragraphs, list items and table cells, without scripts, styles, navigation,
headers, footers or forms. The text is capped so it fits in every planner
request, and it is saved next to the plan so reviewers can see the source.
"""

from html.parser import HTMLParser
import re
from urllib.request import Request, urlopen

MAX_REFERENCE_CHARS = 20000
MAX_DOWNLOAD_BYTES = 3_000_000
SKIPPED = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template", "button"}
BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dt", "dd", "blockquote", "pre", "figcaption",
          "caption", "br", "div", "section", "article", "tr"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipping, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED:
            self.skipping += 1
        elif tag == "title" and not self.skipping:  # Inline SVG icons carry <title> elements too.
            self.in_title = True
        elif tag in BLOCKS:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3") and not self.skipping:
            self.parts.append("## ")
        if tag == "li" and not self.skipping:
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in SKIPPED and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skipping:
            return
        if self.in_title:
            self.title += data
        else:
            self.parts.append(data)


def html_text(html: str) -> str:
    """Readable text of an HTML page: the title, then one block per line."""
    parser = _TextExtractor()
    parser.feed(html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).split("\n")]
    lines = [line for line in lines if line and line not in ("##", "-", "## -")]
    title = re.sub(r"\s+", " ", parser.title).strip()
    return "\n".join(([f"# {title}"] if title else []) + lines)


def fetch_reference(url: str, timeout: float = 30) -> str:
    """Download a page and return its readable text, capped at MAX_REFERENCE_CHARS."""
    if not re.match(r"https?://", url):
        raise ValueError("The reference URL must start with http:// or https://.")
    request = Request(url, headers={"User-Agent": "capstone-script/1.0 (educational explainer videos)"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_DOWNLOAD_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
        kind = response.headers.get_content_type()
    if "html" not in kind and not kind.startswith("text/"):
        raise ValueError(f"{url} is {kind}, not a web page or text file.")
    text = body.decode(charset, errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    text = html_text(text) if "html" in kind else text.strip()
    if len(text) < 200:
        raise ValueError(f"{url} has too little readable text to use as a reference.")
    if len(text) > MAX_REFERENCE_CHARS:
        text = text[:MAX_REFERENCE_CHARS].rsplit("\n", 1)[0] + "\n[Reference shortened to fit the planner request.]"
    return f"Source: {url}\n\n{text}\n"

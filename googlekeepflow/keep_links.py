import re
import webbrowser
from urllib.parse import urlparse


URL_RE = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>'\"`]+)")
TRAILING_PUNCTUATION = ".,;:!?)\]}\"'"


def extract_links(text, limit=20):
    links = []
    seen = set()
    for match in URL_RE.finditer(text or ""):
        url = match.group(1).rstrip(TRAILING_PUNCTUATION)
        if url.lower().startswith("www."):
            url = f"https://{url}"
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        links.append(url)
        if len(links) >= limit:
            break
    return links


def link_title(url):
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split("/", 1)[0] or url
    path = parsed.path.strip("/")
    if path:
        short_path = path[:40] + ("..." if len(path) > 40 else "")
        return f"{host}/{short_path}"
    return host


def open_url(url):
    webbrowser.open(url)


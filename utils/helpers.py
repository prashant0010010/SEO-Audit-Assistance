"""Small shared helpers: URL validation/normalisation, text cleaning, DataFrame export."""
from __future__ import annotations

import ipaddress
import re
import socket
from functools import lru_cache
from urllib.parse import urljoin, urlparse, urlunparse

import config

SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".zip", ".rar",
    ".mp3", ".mp4", ".mov", ".avi", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".css", ".js", ".json", ".xml", ".woff", ".woff2", ".ttf", ".eot", ".gz",
)

FRIENDLY_ERRORS = {
    "invalid_url": "That doesn't look like a valid web address.",
    "blocked_host": "This address points to a private or local network, which this tool will not audit.",
    "timeout": "The website took too long to respond.",
    "ssl": "A secure-connection (SSL/TLS) problem occurred while contacting the website.",
    "connection": "We couldn't connect to the website. Check the address and that the site is online.",
    "redirect_loop": "The page redirects in a loop or through too many redirects.",
    "other": "An unexpected problem occurred while retrieving the page.",
}


def clean_text(value: str | None) -> str:
    """Collapse whitespace; return '' for None."""
    return re.sub(r"\s+", " ", value or "").strip()


def validate_url(raw: str) -> tuple[str | None, str | None]:
    """Return (normalised_url, error_message). Adds https:// when no scheme is given."""
    text = (raw or "").strip()
    if not text:
        return None, "Please enter a website URL."
    if len(text) > 2048 or re.search(r"\s", text):
        return None, FRIENDLY_ERRORS["invalid_url"]
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, "Only http:// and https:// addresses can be audited."
    host = parsed.hostname
    if "." not in host and not (config.ALLOW_PRIVATE_HOSTS and host == "localhost"):
        return None, FRIENDLY_ERRORS["invalid_url"]
    if not is_public_host(host):
        return None, FRIENDLY_ERRORS["blocked_host"]
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, "")), None


@lru_cache(maxsize=512)
def is_public_host(host: str) -> bool:
    """Reject loopback/private/link-local targets (basic SSRF guard for hosted deployments)."""
    if config.ALLOW_PRIVATE_HOSTS:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable: let the request fail normally with a friendly message
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def host_key(url: str) -> str:
    """Host without 'www.' and port, lower-cased — used for same-site comparison."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def norm_key(url: str) -> str:
    """Canonical form used to de-duplicate URLs (no fragment, no trailing slash, no www/default port)."""
    p = urlparse(url)
    path = p.path.rstrip("/") or ""
    return f"{p.scheme}://{host_key(url)}{path}" + (f"?{p.query}" if p.query else "")


def same_site(url: str, site_host: str) -> bool:
    return host_key(url) == site_host


def absolutise(base: str, href: str) -> str | None:
    """Resolve an href to an absolute http(s) URL without fragment; None if not crawlable."""
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "sms:")):
        return None
    try:
        absolute = urljoin(base, href)
        p = urlparse(absolute)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    return urlunparse((p.scheme, p.netloc, p.path or "/", "", p.query, ""))


def looks_like_html_path(url: str) -> bool:
    return not urlparse(url).path.lower().endswith(SKIP_EXTENSIONS)


def short_url(url: str, limit: int = 60) -> str:
    """Display form: drop scheme, truncate long values."""
    p = urlparse(url)
    text = (p.netloc + p.path + (f"?{p.query}" if p.query else "")).rstrip("/") or p.netloc
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural_form or singular + 's')}"


def pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def pages_to_dataframe(pages):
    """Page-level table used by the Pages tab, CSV export and PDF appendix."""
    import pandas as pd

    rows = []
    for p in pages:
        rows.append({
            "URL": p.final_url or p.url,
            "Status": p.status if p.status else "error",
            "Title": p.title,
            "H1": " | ".join(p.h1s),
            "Meta Description": p.meta_description,
            "Canonical": p.canonical,
            "Word Count": p.word_count if p.analysable else None,
            "Schema": ", ".join(p.schema_types) if p.schema_types else ("No" if p.analysable else ""),
            "Issues": "; ".join(p.page_flags),
        })
    return pd.DataFrame(rows)

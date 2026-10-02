"""Polite, limited, same-site crawler. Never raises on a broken page; problems become notes/flags."""
from __future__ import annotations

import re
from collections import deque
from urllib.robotparser import RobotFileParser

import config
from auditor.models import PageResult, SiteInfo
from auditor.technical import parse_html
from utils.helpers import (absolutise, host_key, looks_like_html_path, norm_key, same_site, short_url)
from utils.http import FetchResult, Fetcher, same_origin_root

MAX_DEPTH = 3
LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", re.I | re.S)


def _to_page(url: str, depth: int, via: str, fr: FetchResult) -> PageResult:
    return PageResult(
        url=url, depth=depth, discovered_via=via, status=fr.status, final_url=fr.final_url or url,
        redirect_chain=list(fr.history), error_kind=fr.error_kind, error=fr.error,
        content_type=fr.content_type, is_html=bool(fr.is_html and not fr.error_kind), elapsed=fr.elapsed)


def _load_robots(fetcher: Fetcher, site: SiteInfo) -> RobotFileParser | None:
    site.robots_url = site.origin + "/robots.txt"
    fr = fetcher.get(site.robots_url)
    text = fr.text if (fr.status == 200 and not fr.error_kind) else ""
    looks_html = text.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
    site.robots_status = fr.status
    if not text.strip() or looks_html:
        if fr.error_kind:
            site.notes.append(f"robots.txt could not be retrieved ({fr.error}). Crawling continued normally.")
        return None
    site.robots_exists = True
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    site.robots_sitemaps = [m.strip() for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)]
    site.sitemap_referenced_in_robots = bool(site.robots_sitemaps)
    site.robots_allows_all_crawl = rp.can_fetch(config.USER_AGENT, site.origin + "/")
    return rp


def _load_sitemap(fetcher: Fetcher, site: SiteInfo) -> None:
    candidates = list(site.robots_sitemaps) or []
    default = site.origin + "/sitemap.xml"
    if default not in candidates:
        candidates.append(default)
    for cand in candidates[:3]:
        fr = fetcher.get(cand)
        body = fr.text if (fr.status == 200 and not fr.error_kind) else ""
        low = body[:3000].lower()
        if "<urlset" not in low and "<sitemapindex" not in low:
            continue
        site.sitemap_exists, site.sitemap_url = True, cand
        urls: list[str] = []
        if "<sitemapindex" in low:
            for child in LOC_RE.findall(body)[:3]:        # sample at most three child sitemaps
                cfr = fetcher.get(child)
                if cfr.status == 200 and cfr.text:
                    urls += LOC_RE.findall(cfr.text)[: config.SITEMAP_URL_SAMPLE]
        else:
            urls = LOC_RE.findall(body)[: config.SITEMAP_URL_SAMPLE]
        site.sitemap_urls = urls
        site.sitemap_url_count = len(urls)
        return


def crawl(start_url: str, max_pages: int, fetcher: Fetcher | None = None, progress=None):
    """Crawl up to `max_pages` same-site HTML pages. Returns (pages, site)."""
    fetcher = fetcher or Fetcher()
    site = SiteInfo()
    pages: list[PageResult] = []

    # ---- homepage first
    fr = fetcher.get(start_url)
    home = _to_page(start_url, 0, "start", fr)
    pages.append(home)
    if fr.error_kind or not fr.final_url:
        site.notes.append(f"We couldn't access the website: {fr.error or 'no response'}")
        return pages, site
    site.origin = same_origin_root(fr.final_url)
    site.host = host_key(fr.final_url)
    if host_key(start_url) != site.host:
        site.notes.append(f"The address redirects to {site.host}; the audit treats that as the site.")
    if home.analysable:
        parse_html(home, fr.text, site.host, fr.headers)
    elif home.status >= 400:
        site.notes.append(f"The homepage returned HTTP {home.status}.")
    if progress:
        progress(1, max_pages, home.final_url)

    # ---- robots.txt and sitemap (once per audit)
    rp = _load_robots(fetcher, site)
    _load_sitemap(fetcher, site)
    delay = fetcher.delay
    if rp:
        try:
            cd = rp.crawl_delay(config.USER_AGENT)
            if cd:
                fetcher.delay = max(delay, min(float(cd), 5.0))
        except (TypeError, ValueError):
            pass

    def allowed(url: str) -> bool:
        return True if rp is None else rp.can_fetch(config.USER_AGENT, url)

    # ---- BFS
    seen = {norm_key(start_url), norm_key(home.final_url)}
    crawled_final = {norm_key(home.final_url)}
    queue: deque = deque()
    sitemap_loaded = False

    def enqueue(url: str, depth: int, via: str) -> None:
        k = norm_key(url)
        if k in seen or not same_site(url, site.host) or not looks_like_html_path(url):
            return
        seen.add(k)
        if not allowed(url):
            site.robots_blocked_urls.append(url)
            return
        queue.append((url, depth, via))

    for link in home.internal_links:
        enqueue(link, 1, "link")

    while len(pages) < max_pages:
        if not queue and not sitemap_loaded:
            sitemap_loaded = True
            for loc in site.sitemap_urls:
                u = absolutise(site.origin + "/", loc)
                if u:
                    enqueue(u, 1, "sitemap")
        if not queue:
            break
        url, depth, via = queue.popleft()
        fr = fetcher.get(url)
        page = _to_page(url, depth, via, fr)
        fkey = norm_key(page.final_url)
        if fkey in crawled_final:          # redirected onto a page we already have
            continue
        crawled_final.add(fkey)
        seen.add(fkey)
        if fr.error_kind:
            site.notes.append(f"We couldn't access {short_url(url)} ({fr.error}). "
                              "The audit will continue with the pages that were successfully retrieved.")
        elif not same_site(page.final_url, site.host):
            page.error_kind, page.error = "external_redirect", "Redirects to a different website."
            page.is_html = False
        elif page.status >= 400:
            site.notes.append(f"{short_url(url)} returned HTTP {page.status}.")
        elif page.analysable:
            try:
                parse_html(page, fr.text, site.host, fr.headers)
            except Exception as exc:       # one malformed page must never stop the audit
                page.error_kind, page.error = "other", f"Page could not be analysed ({type(exc).__name__})."
                site.notes.append(f"{short_url(url)} could not be analysed and was skipped.")
        pages.append(page)
        if page.analysable and depth < MAX_DEPTH:
            for link in page.internal_links:
                enqueue(link, depth + 1, "link")
        if progress:
            progress(len(pages), max_pages, page.final_url)

    # ---- who links to whom (for broken-link reporting)
    for p in pages:
        for tgt in p.internal_links:
            site.link_sources.setdefault(norm_key(tgt), set()).add(p.final_url or p.url)

    # ---- verify a limited number of internal links that were not crawled
    crawled_keys = {norm_key(p.url) for p in pages} | {norm_key(p.final_url) for p in pages}
    extra, picked = [], set()
    for p in pages:
        for tgt in p.internal_links:
            k = norm_key(tgt)
            if k in crawled_keys or k in picked or not looks_like_html_path(tgt) or not allowed(tgt):
                continue
            picked.add(k)
            extra.append(tgt)
    for tgt in extra[: config.LINK_CHECK_LIMIT]:
        r = fetcher.head(tgt)
        site.checked_links[tgt] = 0 if r.error_kind else r.status
    site.unchecked_internal_links = max(len(extra) - config.LINK_CHECK_LIMIT, 0)
    if site.unchecked_internal_links:
        site.notes.append(f"{site.unchecked_internal_links} additional internal links were not checked "
                          "(link verification is capped to keep the audit fast).")
    return pages, site

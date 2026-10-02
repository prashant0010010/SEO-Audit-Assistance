"""HTML parsing for a fetched page + site-wide technical SEO checks."""
from __future__ import annotations

import re
from collections import Counter

from bs4 import BeautifulSoup

import config
from auditor import schema as schema_mod
from auditor.content import count_visible_words
from auditor.models import Component, Issue, PageResult, SiteInfo
from utils.helpers import absolutise, clean_text, norm_key, plural, pct, same_site, short_url

ABOUT_RE = re.compile(r"\babout\b|about-us|our-story|who-we-are|our-team|meet-the-team", re.I)
CONTACT_RE = re.compile(r"contact|get-in-touch|enquir|reach-us|book-a-call|request-a-quote", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+\d{1,3}|\b0\d)[\s().-]*\d(?:[\s().-]*\d){6,}")
ARTICLE_PATH_RE = re.compile(r"^/(blog|news|articles?|insights?|posts?|journal|guides?)/[^/]+", re.I)


# ---------------------------------------------------------------- parsing
def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # malformed input or parser problem: fall back to the lenient built-in parser
        return BeautifulSoup(html, "html.parser")


def _directives(value: str) -> tuple[bool, bool]:
    v = (value or "").lower()
    return ("noindex" in v or v.strip() == "none" or "none" in v.split(",")), \
           ("nofollow" in v or v.strip() == "none" or "none" in v.split(","))


def parse_html(page: PageResult, html: str, site_host: str, headers: dict | None = None) -> None:
    """Populate `page` from raw HTML. Any parsing problem is swallowed so one page cannot stop the audit."""
    base = page.final_url or page.url
    try:
        soup = _soup(html)
    except Exception:
        page.error_kind, page.error = "other", "The page's HTML could not be parsed."
        return

    # --- metadata
    page.title = clean_text(soup.title.get_text()) if soup.title else ""
    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    page.meta_description = clean_text(md.get("content")) if md else ""
    html_tag = soup.find("html")
    page.lang = (html_tag.get("lang") or "").strip() if html_tag else ""

    # --- robots directives
    metas = []
    for m in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot|bingbot)$", re.I)}):
        metas.append(m.get("content") or "")
    page.robots_meta = ", ".join(x for x in metas if x)
    page.x_robots = (headers or {}).get("x-robots-tag", "")
    n1, f1 = _directives(page.robots_meta)
    n2, f2 = _directives(page.x_robots)
    page.noindex, page.nofollow = (n1 or n2), (f1 or f2)

    # --- canonical
    link = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    if link and link.get("href"):
        page.canonical = absolutise(base, link["href"]) or ""
        page.canonical_elsewhere = bool(page.canonical) and norm_key(page.canonical) != norm_key(base)

    # --- headings
    page.h1s = [clean_text(h.get_text()) for h in soup.find_all("h1")]
    page.h2_count = len(soup.find_all("h2"))
    page.h3_count = len(soup.find_all("h3"))
    question_heads = sum(1 for h in soup.find_all(["h2", "h3", "h4"]) if clean_text(h.get_text()).endswith("?"))

    # --- links (whole page, including navigation)
    internal, external, seen = [], [], set()
    about_url = contact_url = ""
    contact_link = False
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith(("mailto:", "tel:")):
            contact_link = True
            continue
        url = absolutise(base, href)
        if not url or url in seen:
            continue
        seen.add(url)
        if same_site(url, site_host):
            internal.append(url)
            text = clean_text(a.get_text()) + " " + url.rsplit("/", 2)[-1]
            if not about_url and ABOUT_RE.search(text):
                about_url = url
            if not contact_url and CONTACT_RE.search(text):
                contact_url = url
        else:
            external.append(url)
    page.internal_links, page.external_links = internal, external

    # --- images and mixed content
    for img in soup.find_all("img"):
        if img.get("width") == "1" and img.get("height") == "1":
            continue  # tracking pixel
        page.images_total += 1
        alt = img.get("alt")
        if alt is None:
            page.images_missing_alt += 1
        elif not alt.strip():
            page.images_empty_alt += 1  # valid for decorative images; informational only
    if base.startswith("https://"):
        for tag, attr in (("img", "src"), ("script", "src"), ("iframe", "src"), ("source", "src"),
                          ("video", "src"), ("audio", "src"), ("link", "href")):
            for el in soup.find_all(tag):
                if tag == "link" and "stylesheet" not in (el.get("rel") or []):
                    continue
                if str(el.get(attr) or "").lower().startswith("http://"):
                    page.mixed_content += 1

    # --- structured data
    sd = schema_mod.extract_jsonld(soup)
    page.schema_types, page.schema_errors, page.schema_blocks = sd["types"], sd["errors"], sd["blocks"]
    ent = schema_mod.entity_info(sd["entities"])

    # --- observable signals (collected before navigation/footers are removed)
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    og_type = soup.find("meta", attrs={"property": "og:type"})
    has_author = bool(
        soup.find("meta", attrs={"name": re.compile(r"^author$", re.I)})
        or soup.find(["a", "link"], rel=lambda v: v and "author" in (v if isinstance(v, list) else [v]))
        or soup.find(attrs={"itemprop": "author"})
        or soup.find(class_=re.compile(r"author|byline", re.I))
        or ent["has_author"]
    )
    path = re.sub(r"^https?://[^/]+", "", base)
    path = path.split("?")[0]
    article_like = bool(
        (og_type and (og_type.get("content") or "").lower() == "article")
        or set(page.schema_types) & schema_mod.ARTICLE_TYPES
        or ARTICLE_PATH_RE.match(path)
    )
    text_all = soup.get_text(" ")
    page.signals = {
        "about_url": about_url, "contact_url": contact_url,
        "contact_info": bool(contact_link or EMAIL_RE.search(text_all) or PHONE_RE.search(text_all)
                             or ent["has_contact"]),
        "address": bool(soup.find("address") or ent["has_address"]),
        "has_author": has_author, "article_like": article_like,
        "og_site_name": clean_text(og_site.get("content")) if og_site else "",
        "org_names": ent["org_names"], "schema_org": ent["has_org"], "schema_website": ent["has_website"],
        "schema_contact": ent["has_contact"], "same_as": ent["same_as"],
        "faq_like": bool(question_heads >= 2 or "FAQPage" in page.schema_types
                         or len(soup.find_all("details")) >= 2),
        "lists_tables": len(soup.find_all(["ul", "ol", "table"])),
    }

    # --- visible text (navigation/footer removed) and in-content outbound links
    page.word_count = count_visible_words(soup)
    body_external = 0
    for a in soup.find_all("a", href=True):
        u = absolutise(base, a["href"])
        if u and not same_site(u, site_host):
            body_external += 1
    page.signals["body_external_links"] = body_external


# ---------------------------------------------------------------- site-wide checks
def _issue(id_, sev, cats, title, found, why, action, rec, pages=None, urls=None, count=None) -> Issue:
    u = urls if urls is not None else [p.final_url or p.url for p in (pages or [])]
    return Issue(id=id_, severity=sev, categories=cats, title=title, found=found, why=why,
                 action=action, rec=rec, urls=u, count=count if count is not None else len(u))


def _share_component(name, max_points, good, total, detail_fmt) -> Component:
    if total == 0:
        return Component(name, max_points, 0, "Not applicable (no pages to evaluate)", applicable=False)
    return Component(name, max_points, round(max_points * good / total, 1), detail_fmt)


def compute_inbound(pages: list[PageResult]) -> None:
    keys: dict[str, PageResult] = {}
    for p in pages:
        keys[norm_key(p.url)] = p
        if p.final_url:
            keys[norm_key(p.final_url)] = p
    for p in pages:
        p.inbound_links = 0
    for src in pages:
        for tgt in src.internal_links:
            dest = keys.get(norm_key(tgt))
            if dest is not None and dest is not src:
                dest.inbound_links += 1


def check(pages: list[PageResult], site: SiteInfo) -> tuple[list[Component], list[Issue], list[tuple]]:
    comps: list[Component] = []
    issues: list[Issue] = []
    home = pages[0]
    ok = [p for p in pages if p.analysable]
    relevant = [p for p in pages if not (p.status == 200 and not p.is_html and not p.error_kind)]
    compute_inbound(pages)
    T = ["technical"]

    # ---- 1. Availability
    bad = [p for p in relevant if not p.analysable and p is not home]
    server = [p for p in bad if p.status >= 500]
    unreachable = [p for p in bad if p.status == 0 and p.error_kind not in ("redirect_loop", "external_redirect")]
    comps.append(_share_component(
        "Page availability", 20, len(ok), len(relevant),
        f"{len(ok)} of {len(relevant)} crawled URLs returned a normal HTML page (HTTP 200)."))
    for p in bad:
        if p.error_kind == "external_redirect":
            p.page_flags.append("Redirects to another site")
        else:
            p.page_flags.append(f"HTTP {p.status}" if p.status else f"Unreachable ({p.error_kind or 'error'})")
    if server:
        issues.append(_issue(
            "server_errors", "HIGH", T, "Server errors (5xx) returned",
            f"{plural(len(server), 'crawled URL')} responded with a 5xx server error.",
            "Server errors make content unavailable to users and crawlers and can reduce how often a site is crawled.",
            "Check server logs for these URLs and fix the underlying errors.",
            f"Resolve server errors on {plural(len(server), 'URL')}", server))
    if unreachable:
        issues.append(_issue(
            "unreachable", "MEDIUM", T, "Some URLs could not be retrieved",
            f"{plural(len(unreachable), 'URL')} timed out or failed to connect during the crawl.",
            "Intermittent failures may indicate performance or hosting problems, or bot protection.",
            "Re-test these URLs manually; check hosting stability and any firewall/bot rules.",
            f"Investigate {plural(len(unreachable), 'URL')} that failed to load", unreachable))

    # ---- 2. Indexability
    noidx = [p for p in ok if p.noindex]
    comps.append(_share_component(
        "Indexability (noindex)", 15, len(ok) - len(noidx), len(ok),
        f"{len(ok) - len(noidx)} of {len(ok)} pages have no noindex directive."))
    for p in noidx:
        p.page_flags.append("noindex")
    if noidx:
        sev = "CRITICAL" if home in noidx else "HIGH"
        issues.append(_issue(
            "noindex", sev, T, "Pages carry a noindex directive",
            f"{plural(len(noidx), 'crawled page')} set noindex via meta robots or X-Robots-Tag"
            + (", including the homepage." if home in noidx else "."),
            "Pages marked noindex are asked not to appear in search results. This is correct for private or "
            "utility pages, but harmful if applied to pages meant to attract traffic.",
            "Confirm each of these pages is meant to be excluded; remove noindex from any that should be indexed.",
            f"Review noindex on {plural(len(noidx), 'page')}", noidx))
    nofollow = [p for p in ok if p.nofollow]
    if nofollow:
        issues.append(_issue(
            "nofollow", "LOW", T, "Pages instruct crawlers not to follow links",
            f"{plural(len(nofollow), 'page')} use a nofollow robots directive.",
            "A page-level nofollow stops link signals and crawl discovery passing through that page.",
            "Review whether the page-level nofollow is intentional.",
            f"Review page-level nofollow on {plural(len(nofollow), 'page')}", nofollow))

    # ---- 3. Canonical
    with_canon = [p for p in ok if p.canonical]
    elsewhere = [p for p in with_canon if p.canonical_elsewhere]
    no_canon = [p for p in ok if not p.canonical]
    c1 = _share_component("Canonical tag present", 7, len(with_canon), len(ok),
                          f"{len(with_canon)} of {len(ok)} pages declare a canonical URL.")
    c2 = _share_component("Canonical not pointing elsewhere", 3, len(ok) - len(elsewhere), len(ok),
                          f"{len(elsewhere)} page(s) declare a canonical URL different from their own address.")
    comps += [c1, c2]
    for p in no_canon:
        p.page_flags.append("No canonical")
    for p in elsewhere:
        p.page_flags.append("Canonical points elsewhere")
    if no_canon:
        sev = "MEDIUM" if len(no_canon) >= len(ok) / 2 else "LOW"
        issues.append(_issue(
            "canonical_missing", sev, T, "Canonical tags missing",
            f"{plural(len(no_canon), 'page')} of {len(ok)} have no canonical tag.",
            "A self-referencing canonical helps signal the preferred URL when the same content can be reached "
            "through parameters, trailing slashes or other variants.",
            "Add a self-referencing canonical link element to these pages.",
            f"Add missing canonical tags to {plural(len(no_canon), 'page')}", no_canon))
    if elsewhere:
        issues.append(_issue(
            "canonical_elsewhere", "MEDIUM", T, "Canonical points to a different URL",
            f"{plural(len(elsewhere), 'page')} declare a canonical URL that differs from the page's own address.",
            "This is legitimate for duplicates or parameter variants, but on a primary page it can ask search "
            "engines to ignore the page you want to rank.",
            "Review each case; point canonicals to the page itself unless a different preferred URL is intended.",
            f"Review canonical targets on {plural(len(elsewhere), 'page')}", elsewhere))

    # ---- 4. Titles and descriptions (presence + uniqueness)
    no_title = [p for p in ok if not p.title]
    no_desc = [p for p in ok if not p.meta_description]
    tcount = Counter(p.title.lower() for p in ok if p.title)
    dcount = Counter(p.meta_description.lower() for p in ok if p.meta_description)
    dup_t = [p for p in ok if p.title and tcount[p.title.lower()] > 1]
    dup_d = [p for p in ok if p.meta_description and dcount[p.meta_description.lower()] > 1]
    comps.append(_share_component("Title tag present", 5, len(ok) - len(no_title), len(ok),
                                  f"{len(ok) - len(no_title)} of {len(ok)} pages have a title."))
    comps.append(_share_component("Meta description present", 5, len(ok) - len(no_desc), len(ok),
                                  f"{len(ok) - len(no_desc)} of {len(ok)} pages have a meta description."))
    dup_any = {id(p) for p in dup_t} | {id(p) for p in dup_d}
    comps.append(_share_component("Title and description unique", 5, len(ok) - len(dup_any), len(ok),
                                  f"{len(dup_any)} page(s) share a title or description with another crawled page."))
    for p in no_title:
        p.page_flags.append("Missing title")
    for p in no_desc:
        p.page_flags.append("Missing meta description")
    for p in dup_t:
        p.page_flags.append("Duplicate title")
    for p in dup_d:
        p.page_flags.append("Duplicate meta description")
    TC = ["technical", "content"]
    if no_title:
        issues.append(_issue(
            "title_missing", "HIGH", TC, "Missing title tags",
            f"{plural(len(no_title), 'page')} have no title element.",
            "The title is a primary on-page signal and often the headline shown in search results.",
            "Write a unique, descriptive title for each of these pages.",
            f"Add title tags to {plural(len(no_title), 'page')}", no_title))
    if no_desc:
        issues.append(_issue(
            "desc_missing", "MEDIUM", TC, "Missing meta descriptions",
            f"{plural(len(no_desc), 'page')} have no meta description.",
            "Search engines may write their own snippet, but a good description gives you control over how the "
            "page is summarised and can influence click-through.",
            "Write a concise, page-specific description (roughly 70\u2013160 characters) for each page.",
            f"Add meta descriptions to {plural(len(no_desc), 'page')}", no_desc))
    if dup_t:
        issues.append(_issue(
            "title_duplicate", "MEDIUM", TC, "Duplicate title tags",
            f"{plural(len(dup_t), 'page')} share a title with another crawled page.",
            "Identical titles make it harder to distinguish pages for users and search engines.",
            "Give each page a title that reflects its specific topic.",
            f"Make titles unique on {plural(len(dup_t), 'page')}", dup_t))
    if dup_d:
        issues.append(_issue(
            "desc_duplicate", "LOW", TC, "Duplicate meta descriptions",
            f"{plural(len(dup_d), 'page')} share a meta description with another crawled page.",
            "Repeated descriptions add little value and can produce near-identical snippets.",
            "Write page-specific descriptions.",
            f"Make meta descriptions unique on {plural(len(dup_d), 'page')}", dup_d))

    # ---- 5. H1
    no_h1 = [p for p in ok if not p.h1s]
    multi_h1 = [p for p in ok if len(p.h1s) > 1]
    h1_points = sum(0 if not p.h1s else (1 if len(p.h1s) == 1 else 0.5) for p in ok)
    comps.append(_share_component(
        "H1 heading", 10, h1_points, len(ok),
        f"{len(no_h1)} page(s) without an H1; {len(multi_h1)} with more than one (half credit)."))
    for p in no_h1:
        p.page_flags.append("Missing H1")
    for p in multi_h1:
        p.page_flags.append("Multiple H1s")
    if no_h1:
        issues.append(_issue(
            "h1_missing", "MEDIUM", TC, "Pages without an H1",
            f"{plural(len(no_h1), 'page')} have no H1 heading.",
            "The H1 usually states the main topic of the page and helps users and crawlers understand it.",
            "Add one clear H1 to each of these pages.",
            f"Add an H1 to {plural(len(no_h1), 'page')}", no_h1))
    if multi_h1:
        issues.append(_issue(
            "h1_multiple", "LOW", TC, "Pages with multiple H1s",
            f"{plural(len(multi_h1), 'page')} contain more than one H1.",
            "Multiple H1s are permitted in HTML5, but a single clear H1 usually keeps the page focus unambiguous.",
            "Review whether one H1 would describe the page more clearly.",
            f"Review multiple H1s on {plural(len(multi_h1), 'page')}", multi_h1))

    # ---- 6. Internal links: broken + orphan-like
    broken: list[tuple] = []
    targets_total = 0
    for p in pages:
        if p is home:
            continue
        targets_total += 1
        if (not p.analysable and not (p.status == 200 and not p.is_html)
                and p.error_kind not in ("blocked_host", "external_redirect")):
            srcs = site.link_sources.get(norm_key(p.url), set())
            for s in sorted(srcs):
                broken.append((s, p.url, p.status or p.error_kind or "error"))
    for url, status in site.checked_links.items():
        targets_total += 1
        if status == 0 or status >= 400:
            for s in sorted(site.link_sources.get(norm_key(url), set())):
                broken.append((s, url, status or "error"))
    broken_targets = sorted({b[1] for b in broken})
    comps.append(_share_component(
        "Internal links not broken", 6, max(targets_total - len(broken_targets), 0), targets_total,
        f"{len(broken_targets)} of {targets_total} internal URLs checked returned an error."))
    candidates = [p for p in ok if p is not home]
    orphans = [p for p in candidates if p.inbound_links == 0]
    comps.append(_share_component(
        "No orphan-like pages", 4, len(candidates) - len(orphans), len(candidates),
        f"{len(orphans)} crawled page(s) received no internal link from the other crawled pages."))
    for p in orphans:
        p.page_flags.append("Orphan-like")
    if broken_targets:
        sev = "HIGH" if len(broken_targets) >= 3 else "MEDIUM"
        issues.append(_issue(
            "broken_links", sev, T, "Broken internal links",
            f"{plural(len(broken_targets), 'internal URL')} return an error status, referenced by "
            f"{plural(len(broken), 'link')} on the crawled pages.",
            "Broken internal links can prevent users and crawlers from reaching intended content and waste crawl "
            "effort.",
            "Review the affected URLs and update or remove the broken links, or redirect the old URLs.",
            f"Fix {plural(len(broken_targets), 'broken internal URL')} ({plural(len(broken), 'link')})",
            urls=broken_targets, count=len(broken)))
    if orphans:
        issues.append(_issue(
            "orphans", "LOW", T, "Orphan-like pages in the sampled crawl",
            f"{plural(len(orphans), 'page')} were not linked from any other crawled page (found via the sitemap).",
            "Pages with no internal links are hard for users and crawlers to discover. This is based on a limited "
            "crawl, so some pages may be linked from pages that were not crawled.",
            "Check whether these pages are linked from navigation or related content, and add links where useful.",
            f"Link to {plural(len(orphans), 'orphan-like page')} from relevant pages", orphans))

    # ---- 7. Images
    total_img = sum(p.images_total for p in ok)
    miss_img = sum(p.images_missing_alt for p in ok)
    if total_img:
        comps.append(Component("Images with alt attribute", 5, round(5 * (total_img - miss_img) / total_img, 1),
                               f"{total_img - miss_img} of {total_img} images ({pct(total_img - miss_img, total_img)}%) "
                               "have an alt attribute."))
    else:
        comps.append(Component("Images with alt attribute", 5, 0, "No images found in crawled pages.", False))
    miss_pages = [p for p in ok if p.images_missing_alt]
    for p in miss_pages:
        p.page_flags.append(f"{p.images_missing_alt} image(s) without alt")
    if miss_img:
        sev = "MEDIUM" if miss_img / total_img > 0.5 and miss_img >= 10 else "LOW"
        issues.append(_issue(
            "img_alt", sev, T, "Images without alt text",
            f"{miss_img} of {total_img} images ({pct(miss_img, total_img)}%) have no alt attribute, across "
            f"{plural(len(miss_pages), 'page')}.",
            "Alt text supports accessibility and helps search engines understand image content. "
            "Purely decorative images can use an empty alt attribute.",
            "Add concise, descriptive alt text to meaningful images; use alt=\"\" for decorative ones.",
            f"Add alt text to {miss_img} image(s)", miss_pages, count=miss_img))

    # ---- 8. Technical files
    comps.append(Component("robots.txt present", 4, 4 if site.robots_exists else 0,
                           "robots.txt found." if site.robots_exists else "No robots.txt found."))
    comps.append(Component("XML sitemap present", 4, 4 if site.sitemap_exists else 0,
                           f"Sitemap found ({site.sitemap_url_count} URLs)." if site.sitemap_exists
                           else "No sitemap found at the standard location or in robots.txt."))
    comps.append(Component("Sitemap referenced in robots.txt", 2, 2 if site.sitemap_referenced_in_robots else 0,
                           "robots.txt references a sitemap." if site.sitemap_referenced_in_robots
                           else "robots.txt has no Sitemap: line."))
    if not site.robots_exists:
        issues.append(_issue(
            "robots_missing", "LOW", T, "No robots.txt file found",
            f"{site.robots_url or 'robots.txt'} did not return a valid file.",
            "robots.txt is the standard place to give crawlers guidance and to point to the sitemap.",
            "Add a robots.txt file that allows crawling of important content and references the sitemap.",
            "Add a robots.txt file", urls=[site.robots_url], count=1))
    if not site.sitemap_exists:
        issues.append(_issue(
            "sitemap_missing", "MEDIUM", T, "No XML sitemap found",
            "No sitemap was found at /sitemap.xml or via robots.txt.",
            "Sitemaps help search engines discover and prioritise URLs, especially on larger or newer sites.",
            "Publish an XML sitemap listing canonical, indexable URLs and submit it in Search Console.",
            "Create and publish an XML sitemap", urls=[], count=1))
    elif site.robots_exists and not site.sitemap_referenced_in_robots:
        issues.append(_issue(
            "sitemap_not_in_robots", "LOW", T, "Sitemap not referenced in robots.txt",
            "A sitemap exists but robots.txt does not contain a Sitemap: line.",
            "Referencing the sitemap in robots.txt makes it discoverable to any crawler.",
            f"Add a line such as 'Sitemap: {site.sitemap_url}' to robots.txt.",
            "Reference the sitemap in robots.txt", urls=[site.sitemap_url], count=1))
    if not site.robots_allows_all_crawl:
        issues.append(_issue(
            "robots_blocks_all", "HIGH", T, "robots.txt disallows the homepage for crawlers",
            "The robots.txt rules for this tool's user agent block the root of the site.",
            "If this applies to search engine crawlers it would prevent the site from being crawled.",
            "Confirm the rule is intentional (for example on a staging site) and relax it if not.",
            "Review robots.txt rules blocking the site root", urls=[site.robots_url], count=1))
    if site.robots_blocked_urls:
        issues.append(_issue(
            "robots_blocked", "LOW", T, "Some discovered URLs are disallowed by robots.txt",
            f"{plural(len(site.robots_blocked_urls), 'discovered URL')} were skipped because robots.txt "
            "disallows them.",
            "This is often intentional; it is flagged so you can confirm important pages are not blocked.",
            "Check the list and confirm none of these URLs should be crawlable.",
            f"Confirm {plural(len(site.robots_blocked_urls), 'robots.txt-blocked URL')} are meant to be blocked",
            urls=site.robots_blocked_urls, count=len(site.robots_blocked_urls)))

    # ---- 9. HTTPS / mixed content
    comps.append(Component("Site served over HTTPS", 3, 3 if home.is_https else 0,
                           "Homepage final URL uses HTTPS." if home.is_https else "Homepage final URL is HTTP."))
    https_ok = [p for p in ok if p.is_https]
    mixed = [p for p in https_ok if p.mixed_content]
    comps.append(_share_component("No mixed-content indicators", 2, len(https_ok) - len(mixed), len(https_ok),
                                  f"{len(mixed)} HTTPS page(s) reference http:// resources."))
    for p in mixed:
        p.page_flags.append("Mixed content")
    if not home.is_https:
        issues.append(_issue(
            "no_https", "HIGH", T, "Site is not served over HTTPS",
            f"The homepage resolved to {home.final_url}.",
            "HTTPS protects users, is a lightweight ranking signal, and browsers warn on insecure pages.",
            "Install a certificate and redirect all HTTP URLs to HTTPS.",
            "Move the site to HTTPS", urls=[home.final_url], count=1))
    if mixed:
        issues.append(_issue(
            "mixed_content", "MEDIUM", T, "Mixed-content indicators",
            f"{plural(len(mixed), 'HTTPS page')} reference resources using http:// "
            "(detected from the HTML source only).",
            "Insecure resources on secure pages may be blocked or trigger browser warnings.",
            "Update these resource URLs to HTTPS.",
            f"Fix http:// resources on {plural(len(mixed), 'page')}", mixed))

    # ---- info-level: redirects, long URLs
    chains = [p for p in pages if len(p.redirect_chain) >= 2]
    for p in pages:
        if p.redirected:
            p.page_flags.append("Redirects")
    if chains:
        issues.append(_issue(
            "redirect_chains", "LOW", T, "Redirect chains",
            f"{plural(len(chains), 'URL')} passed through two or more redirects before resolving.",
            "Each extra hop adds latency and can dilute signals.",
            "Link directly to the final URL and collapse chains into a single redirect.",
            f"Shorten redirect chains on {plural(len(chains), 'URL')}", chains))
    loops = [p for p in pages if p.error_kind == "redirect_loop"]
    if loops:
        issues.append(_issue(
            "redirect_loops", "HIGH", T, "Redirect loops",
            f"{plural(len(loops), 'URL')} could not load because of a redirect loop or too many redirects.",
            "Looping URLs cannot be loaded by users or crawlers.",
            "Fix the redirect rules for these URLs.",
            f"Fix redirect loops on {plural(len(loops), 'URL')}", loops))
    long_urls = [p for p in ok if p.url_length > config.LONG_URL]
    for p in long_urls:
        p.page_flags.append("Long URL")
    if long_urls:
        issues.append(_issue(
            "long_urls", "LOW", T, "Very long URLs",
            f"{plural(len(long_urls), 'URL')} exceed {config.LONG_URL} characters.",
            "Long URLs are harder to read, share and maintain.",
            "Shorten URLs where practical (and redirect old versions).",
            f"Review {plural(len(long_urls), 'long URL')}", long_urls))

    return comps, issues, broken

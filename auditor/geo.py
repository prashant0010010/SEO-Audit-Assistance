"""AI Search Readiness: observable signals that may help content be understood and attributed.

This is an internal heuristic. It does NOT predict whether any AI system will rank, retrieve or cite a site.
"""
from __future__ import annotations

import re
import statistics

import config
from auditor.models import Component, Issue
from utils.helpers import host_key, plural

SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "govt", "org"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def brand_from(client_name: str, domain: str) -> str:
    if client_name and client_name.strip():
        return client_name.strip()
    parts = host_key("https://" + domain).split(".")
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _comp(name, max_points, earned, detail, applicable=True) -> Component:
    return Component(name, max_points, round(earned, 1), detail, applicable)


def check(pages, site, client_name: str, domain: str):
    """Return (components, issues, signals) where signals = [(signal, observed, detail), ...]."""
    ok = [p for p in pages if p.analysable]
    comps: list[Component] = []
    issues: list[Issue] = []
    signals: list[tuple] = []
    A = ["ai"]
    if not ok:
        return [Component("AI Search Readiness", 100, 0, "No pages could be analysed.", False)], issues, signals

    n = len(ok)
    home = ok[0] if ok[0] is pages[0] else None
    brand = brand_from(client_name, domain)
    brand_n = _norm(brand)

    # ---------------- 1. Structured data (25)
    valid = [p for p in ok if p.schema_types and not p.schema_errors]
    comps.append(_comp("Structured data coverage", 15, 15 * len(valid) / n,
                       f"{len(valid)} of {n} pages have parseable JSON-LD."))
    has_org = any(p.signals.get("schema_org") for p in ok)
    has_site = any(p.signals.get("schema_website") for p in ok)
    comps.append(_comp("Organisation / WebSite entity markup", 10, (7 if has_org else 0) + (3 if has_site else 0),
                       f"Organization/LocalBusiness markup: {'yes' if has_org else 'no'}; "
                       f"WebSite markup: {'yes' if has_site else 'no'}."))
    all_types = sorted({t for p in ok for t in p.schema_types})
    signals.append(("Structured data (JSON-LD)", "Yes" if valid else "No",
                    f"{len(valid)} of {n} pages. Types: {', '.join(all_types) or 'none detected'}."))
    if all_types and not has_org:
        issues.append(Issue(
            "no_org_schema", "MEDIUM", A, "No Organization or LocalBusiness markup",
            "Structured data was found, but none describes the organisation itself.",
            "Organisation markup states the business name, contact details and official profiles in a "
            "machine-readable way, which may help systems attribute content to the right entity.",
            "Add Organization or LocalBusiness JSON-LD (name, url, logo, address/contact, sameAs profiles) "
            "to the homepage or all pages.",
            "Improve entity and organisation information: add Organization/LocalBusiness markup",
            urls=[], count=1))

    # ---------------- 2. Entity clarity (20)
    brand_in_home = False
    if home is not None:
        fields = [home.title, " ".join(home.h1s), home.signals.get("og_site_name", "")]
        brand_in_home = bool(brand_n) and any(brand_n in _norm(f) for f in fields)
    comps.append(_comp("Business name on homepage", 8, 8 if brand_in_home else 0,
                       f"'{brand}' {'found' if brand_in_home else 'not found'} in the homepage title, H1 or "
                       "og:site_name."))
    org_names = [nm for p in ok for nm in p.signals.get("org_names", [])]
    distinct = {_norm(x) for x in org_names}
    if not org_names:
        sch_pts, sch_detail = 0, "No organisation name found in structured data."
    elif len(distinct) == 1:
        sch_pts, sch_detail = 7, f"Organisation name in schema is consistent ('{org_names[0]}')."
    else:
        sch_pts, sch_detail = 4, f"Organisation name varies across schema ({len(distinct)} variants)."
    comps.append(_comp("Organisation name in structured data", 7, sch_pts, sch_detail))
    in_titles = [p for p in ok if brand_n and brand_n in _norm(p.title)]
    comps.append(_comp("Business name consistent in titles", 5, 5 * len(in_titles) / n,
                       f"'{brand}' appears in {len(in_titles)} of {n} page titles."))
    signals.append(("Clear business identity", "Yes" if brand_in_home else "No",
                    f"'{brand}' {'appears' if brand_in_home else 'was not found'} in the homepage title/H1/"
                    "og:site_name."))
    signals.append(("Consistent business information",
                    "Yes" if len(distinct) <= 1 and org_names else ("Partial" if org_names else "No data"),
                    sch_detail))
    if home is not None and not brand_in_home:
        issues.append(Issue(
            "brand_missing", "LOW", A, "Business name not prominent on the homepage",
            f"'{brand}' was not found in the homepage title, H1 or og:site_name.",
            "A clearly stated business name helps people and machines connect the site with the right "
            "organisation. (If the name entered differs from how the business brands itself, ignore this.)",
            "State the business name in the homepage title and main heading.",
            "Improve entity and organisation information: show the business name clearly on the homepage",
            urls=[home.final_url], count=1))
    if len(distinct) > 1:
        issues.append(Issue(
            "org_name_inconsistent", "LOW", A, "Organisation name differs across structured data",
            f"{len(distinct)} different organisation names appear in JSON-LD: "
            + ", ".join(sorted(set(org_names))[:4]) + ".",
            "Inconsistent naming can make it unclear that references describe the same organisation.",
            "Use one consistent legal/trading name across structured data, titles and contact details.",
            "Make the organisation name consistent across markup", urls=[], count=len(distinct)))

    # ---------------- 3. About / contact (15)
    about = next((p.signals["about_url"] for p in ok if p.signals.get("about_url")), "")
    if not about:
        about = next((p.final_url for p in ok if re.search(r"/about", p.final_url, re.I)), "")
    contact = next((p.signals["contact_url"] for p in ok if p.signals.get("contact_url")), "")
    if not contact:
        contact = next((p.final_url for p in ok if re.search(r"/contact", p.final_url, re.I)), "")
    contact_info = any(p.signals.get("contact_info") or p.signals.get("address") for p in ok)
    comps.append(_comp("About page", 5, 5 if about else 0,
                       f"About page link found ({about})." if about else "No About page link found."))
    comps.append(_comp("Contact page", 5, 5 if contact else 0,
                       f"Contact page link found ({contact})." if contact else "No Contact page link found."))
    comps.append(_comp("Contact details visible", 5, 5 if contact_info else 0,
                       "Email, phone, address or contact markup detected." if contact_info
                       else "No email, phone, address or contact markup detected."))
    signals.append(("About information", "Yes" if about else "No", about or "No About link in the crawled pages."))
    signals.append(("Contact information", "Yes" if (contact or contact_info) else "No",
                    f"Contact page: {'yes' if contact else 'no'}; details on page/in schema: "
                    f"{'yes' if contact_info else 'no'}."))
    if not about:
        issues.append(Issue(
            "no_about", "LOW", A, "No About page found in the crawl",
            "No link to an About page was detected on the crawled pages.",
            "An About page is a common place to state who the organisation is, what it does and who is behind it, "
            "which supports trust and attribution.",
            "Add (or link prominently to) an About page describing the organisation, its services and people.",
            "Improve entity and organisation information: add or link an About page",
            urls=[], count=1))
    if not contact and not contact_info:
        issues.append(Issue(
            "no_contact", "MEDIUM", A, "No contact information detected",
            "No contact page link, email, phone number or address was detected on the crawled pages.",
            "Visible contact details help users and systems confirm that a real, reachable business stands "
            "behind the content.",
            "Add contact details (and LocalBusiness/Organization contact markup where relevant) in a prominent, "
            "crawlable place.",
            "Improve entity and organisation information: add clear contact details",
            urls=[], count=1))

    # ---------------- 4. Content structure (20)
    text_pages = [p for p in ok if p.word_count >= config.THIN_WORDS]
    structured = [p for p in text_pages if p.h1s and (p.h2_count + p.h3_count) >= 2]
    if text_pages:
        comps.append(_comp("Descriptive heading structure", 10, 10 * len(structured) / len(text_pages),
                           f"{len(structured)} of {len(text_pages)} text-rich pages have an H1 plus at least "
                           "two subheadings."))
    else:
        comps.append(_comp("Descriptive heading structure", 10, 0, "No text-rich pages to evaluate.", False))
    med = statistics.median(p.word_count for p in ok)
    depth_pts = 5 if med >= config.GOOD_WORDS else (3 if med >= config.THIN_WORDS else 0)
    comps.append(_comp("Descriptive page content", 5, depth_pts,
                       f"Median visible word count is {int(med)} (full credit at {config.GOOD_WORDS}+)."))
    faq = [p for p in ok if p.signals.get("faq_like")]
    comps.append(_comp("FAQ-style content", 5, 5 if faq else 0,
                       f"FAQ-style content or FAQPage markup on {plural(len(faq), 'page')}." if faq
                       else "No FAQ-style headings, accordions or FAQPage markup detected."))
    signals.append(("Descriptive headings", "Yes" if text_pages and len(structured) >= len(text_pages) / 2
                    else ("Partial" if structured else "No"),
                    f"{len(structured)} of {len(text_pages)} text-rich pages." if text_pages
                    else "No text-rich pages."))
    signals.append(("Descriptive page content", "Yes" if med >= config.GOOD_WORDS else
                    ("Partial" if med >= config.THIN_WORDS else "No"), f"Median {int(med)} words per page."))
    signals.append(("FAQ-style content", "Yes" if faq else "No",
                    f"{len(faq)} page(s)." if faq else "None detected (not needed for every site)."))
    weak = [p for p in text_pages if p not in structured]
    if weak:
        issues.append(Issue(
            "weak_headings", "LOW", A, "Text-rich pages with limited heading structure",
            f"{plural(len(weak), 'page')} have 150+ words but lack an H1 or at least two subheadings.",
            "Clear, descriptive headings break content into topics that are easier for people and machines to "
            "interpret and quote accurately.",
            "Add an H1 and descriptive subheadings that name the topics the page covers.",
            f"Strengthen heading structure on {plural(len(weak), 'page')}",
            urls=[p.final_url for p in weak], count=len(weak)))
    if not faq:
        issues.append(Issue(
            "no_faq", "LOW", A, "No FAQ-style content detected",
            "No question-style headings, accordions or FAQPage markup were found.",
            "Where visitors commonly ask questions, concise question-and-answer content can make information "
            "easy to find and quote. It is not appropriate for every site or page.",
            "Consider an FAQ section on key service or product pages if it reflects real customer questions.",
            "Consider FAQ-style content where customers commonly ask questions", urls=[], count=1))

    # ---------------- 5. Attribution (10, only if article-like pages exist)
    articles = [p for p in ok if p.signals.get("article_like")]
    if articles:
        with_author = [p for p in articles if p.signals.get("has_author")]
        with_src = [p for p in articles if p.signals.get("body_external_links", 0) >= 1]
        comps.append(_comp("Author information on articles", 5, 5 * len(with_author) / len(articles),
                           f"{len(with_author)} of {len(articles)} article-like pages show author information."))
        comps.append(_comp("Source references on articles", 5, 5 * len(with_src) / len(articles),
                           f"{len(with_src)} of {len(articles)} article-like pages link to external sources."))
        no_auth = [p for p in articles if p not in with_author]
        no_src = [p for p in articles if p not in with_src]
        signals.append(("Author information", "Yes" if len(with_author) == len(articles) else
                        ("Partial" if with_author else "No"), f"{len(with_author)} of {len(articles)} article-like pages."))
        signals.append(("Source / citation references", "Yes" if len(with_src) == len(articles) else
                        ("Partial" if with_src else "No"), f"{len(with_src)} of {len(articles)} article-like pages."))
        if no_auth:
            issues.append(Issue(
                "no_author", "LOW", A, "Articles without visible author information",
                f"{plural(len(no_auth), 'article-like page')} show no author or byline.",
                "Named authors with credentials help readers judge expertise and give systems a clear source "
                "to attribute.",
                "Add bylines (and author pages or Person markup) to articles where authorship matters.",
                f"Add author information to {plural(len(no_auth), 'article')}",
                urls=[p.final_url for p in no_auth], count=len(no_auth)))
        if no_src:
            issues.append(Issue(
                "no_sources", "LOW", A, "Articles without outbound source references",
                f"{plural(len(no_src), 'article-like page')} link to no external sources.",
                "Where claims or statistics are used, citing sources supports credibility and verifiability.",
                "Reference reputable sources for factual claims where relevant.",
                f"Add source references to {plural(len(no_src), 'article')}",
                urls=[p.final_url for p in no_src], count=len(no_src)))
    else:
        comps.append(_comp("Attribution signals", 10, 0,
                           "Not applicable: no article-like pages in this crawl.", False))
        signals.append(("Author / source attribution", "N/A", "No article-like pages found in the crawl."))

    # ---------------- 6. Internal linking (10)
    linked = [p for p in ok if len(p.internal_links) >= config.MIN_INTERNAL_LINKS]
    comps.append(_comp("Internal link coverage", 5, 5 * len(linked) / n,
                       f"{len(linked)} of {n} pages have {config.MIN_INTERNAL_LINKS}+ internal links."))
    candidates = [p for p in ok if p is not pages[0]]
    orphans = [p for p in candidates if p.inbound_links == 0]
    if candidates:
        comps.append(_comp("Pages reachable via internal links", 5, 5 * (len(candidates) - len(orphans)) / len(candidates),
                           f"{len(candidates) - len(orphans)} of {len(candidates)} pages are linked from another "
                           "crawled page."))
    else:
        comps.append(_comp("Pages reachable via internal links", 5, 0, "Only one page crawled.", False))
    signals.append(("Internal linking", "Yes" if len(linked) >= n * 0.8 else ("Partial" if linked else "No"),
                    f"{len(linked)} of {n} pages with {config.MIN_INTERNAL_LINKS}+ internal links; "
                    f"{len(orphans)} orphan-like."))
    return comps, issues, signals

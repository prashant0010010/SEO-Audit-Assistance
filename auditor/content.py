"""Content signals: visible word count and per-page content checks. Wording is deliberately cautious."""
from __future__ import annotations

import re

import config
from auditor.models import Component, Issue
from utils.helpers import plural

WORD_RE = re.compile(r"[^\W_]+(?:['\u2019-][^\W_]+)*", re.UNICODE)
STRIP_TAGS = ("script", "style", "noscript", "svg", "template", "nav", "footer", "header", "aside", "form")


def count_visible_words(soup) -> int:
    """Count words in the main visible text. NOTE: removes boilerplate tags from `soup` in place."""
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return len(WORD_RE.findall(root.get_text(" ")))


def _credit(value: float, full: bool, partial: bool) -> float:
    return 1.0 if full else (value if partial else 0.0)


def check(pages) -> tuple[list[Component], list[Issue]]:
    ok = [p for p in pages if p.analysable]
    comps: list[Component] = []
    issues: list[Issue] = []
    n = len(ok)
    if n == 0:
        return [Component("Content signals", 100, 0, "No pages could be analysed.", False)], issues
    C = ["content"]

    # --- title quality (length)
    pts, off = 0.0, []
    for p in ok:
        L = len(p.title)
        if config.TITLE_MIN <= L <= config.TITLE_MAX:
            pts += 1
        elif L:
            pts += 0.5
            off.append(p)
            p.page_flags.append(f"Title length {L}")
    comps.append(Component("Title quality (length)", 20, round(20 * pts / n, 1),
                           f"{n - len(off) - sum(1 for p in ok if not p.title)} of {n} titles are "
                           f"{config.TITLE_MIN}\u2013{config.TITLE_MAX} characters; others get partial or no credit."))
    if off:
        issues.append(Issue(
            "title_length", "LOW", C, "Title length outside the typical range",
            f"{plural(len(off), 'page')} have titles shorter than {config.TITLE_MIN} or longer than "
            f"{config.TITLE_MAX} characters.",
            "Very long titles are often truncated in search results; very short ones may not describe the page.",
            "Review these titles; aim for a clear, descriptive title that fits the typical display width.",
            f"Review title length on {plural(len(off), 'page')}",
            urls=[p.final_url for p in off], count=len(off)))

    # --- description quality (length)
    pts, off = 0.0, []
    for p in ok:
        L = len(p.meta_description)
        if config.DESC_MIN <= L <= config.DESC_MAX:
            pts += 1
        elif L:
            pts += 0.5
            off.append(p)
            p.page_flags.append(f"Description length {L}")
    good_desc = n - len(off) - sum(1 for p in ok if not p.meta_description)
    comps.append(Component("Meta description quality (length)", 20, round(20 * pts / n, 1),
                           f"{good_desc} of {n} descriptions are {config.DESC_MIN}\u2013{config.DESC_MAX} "
                           "characters; others get partial or no credit."))
    if off:
        issues.append(Issue(
            "desc_length", "LOW", C, "Meta description length outside the typical range",
            f"{plural(len(off), 'page')} have descriptions shorter than {config.DESC_MIN} or longer than "
            f"{config.DESC_MAX} characters.",
            "Descriptions that are too long are often truncated; very short ones add little context.",
            "Review these descriptions and aim for a concise, page-specific summary.",
            f"Review description length on {plural(len(off), 'page')}",
            urls=[p.final_url for p in off], count=len(off)))

    # --- headings: H1 present (10) + H2 structure on pages with enough text (10)
    h1_ok = sum(1 for p in ok if p.h1s)
    comps.append(Component("H1 present", 10, round(10 * h1_ok / n, 1), f"{h1_ok} of {n} pages have an H1."))
    long_pages = [p for p in ok if p.word_count >= config.THIN_WORDS]
    no_h2 = [p for p in long_pages if p.h2_count == 0]
    if long_pages:
        comps.append(Component("Subheadings on text-rich pages", 10,
                               round(10 * (len(long_pages) - len(no_h2)) / len(long_pages), 1),
                               f"{len(long_pages) - len(no_h2)} of {len(long_pages)} pages with "
                               f"{config.THIN_WORDS}+ words use H2 subheadings."))
    else:
        comps.append(Component("Subheadings on text-rich pages", 10, 0,
                               "No pages with enough text to evaluate.", False))
    for p in no_h2:
        p.page_flags.append("No H2 subheadings")
    if no_h2:
        issues.append(Issue(
            "no_h2", "LOW", C, "Longer pages without subheadings",
            f"{plural(len(no_h2), 'page')} with {config.THIN_WORDS}+ words have no H2 headings.",
            "Descriptive subheadings help readers scan a page and make its structure clearer to machines.",
            "Consider breaking longer content into sections with descriptive H2 headings.",
            f"Add subheadings to {plural(len(no_h2), 'longer page')}",
            urls=[p.final_url for p in no_h2], count=len(no_h2)))

    # --- depth
    depth_pts, thin, very_thin = 0.0, [], []
    for p in ok:
        w = p.word_count
        if w >= config.GOOD_WORDS:
            depth_pts += 1
        elif w >= config.THIN_WORDS:
            depth_pts += 0.75
        elif w >= config.VERY_THIN_WORDS:
            depth_pts += 0.4
            thin.append(p)
            p.page_flags.append("Thin text \u2013 review recommended")
        else:
            very_thin.append(p)
            p.page_flags.append("Very little visible text \u2013 review recommended")
    comps.append(Component("Content depth signals", 25, round(25 * depth_pts / n, 1),
                           f"Median {sorted(p.word_count for p in ok)[n // 2]} words per page; "
                           f"{len(thin) + len(very_thin)} page(s) under {config.THIN_WORDS} words. "
                           "Word count is a signal, not a quality verdict."))
    if very_thin:
        issues.append(Issue(
            "very_thin", "MEDIUM", C, "Pages with very little visible text",
            f"{plural(len(very_thin), 'page')} have fewer than {config.VERY_THIN_WORDS} words of visible text "
            "in the main content.",
            "Pages with minimal text give search engines little to interpret. Some page types (galleries, "
            "tools, contact pages) legitimately have little text, and content loaded by JavaScript is not "
            "visible to this tool.",
            "Review recommended: confirm whether these pages need more descriptive content or are rendered by "
            "JavaScript.",
            f"Review {plural(len(very_thin), 'page')} with very little visible text",
            urls=[p.final_url for p in very_thin], count=len(very_thin)))
    if thin:
        issues.append(Issue(
            "thin", "LOW", C, "Pages with limited text",
            f"{plural(len(thin), 'page')} have between {config.VERY_THIN_WORDS} and {config.THIN_WORDS} words "
            "of visible text.",
            "Short pages can rank well when they fully answer the query, so this is a prompt for review rather "
            "than a defect.",
            "Review recommended: check whether the content fully covers what a visitor would expect to find.",
            f"Review {plural(len(thin), 'short page')}",
            urls=[p.final_url for p in thin], count=len(thin)))

    # --- internal linking
    few = [p for p in ok if len(p.internal_links) < config.MIN_INTERNAL_LINKS]
    comps.append(Component("Internal linking", 15, round(15 * (n - len(few)) / n, 1),
                           f"{n - len(few)} of {n} pages link to at least {config.MIN_INTERNAL_LINKS} "
                           "other internal URLs."))
    for p in few:
        p.page_flags.append("Few internal links")
    if few:
        issues.append(Issue(
            "few_links", "LOW", C, "Pages with very few internal links",
            f"{plural(len(few), 'page')} link to fewer than {config.MIN_INTERNAL_LINKS} internal URLs.",
            "Internal links help visitors and crawlers move between related content.",
            "Review whether these pages should link to related pages or key service/product pages.",
            f"Add internal links on {plural(len(few), 'page')}",
            urls=[p.final_url for p in few], count=len(few)))
    return comps, issues

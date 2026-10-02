"""Structured data (JSON-LD) extraction and checks. Malformed JSON-LD is counted, never fatal."""
from __future__ import annotations

import json

from auditor.models import Issue
from utils.helpers import plural

COMMON_TYPES = {
    "Organization", "LocalBusiness", "Product", "Article", "FAQPage", "BreadcrumbList",
    "WebSite", "Person", "NewsArticle", "BlogPosting", "Service", "WebPage", "ProfessionalService",
}
ORG_TYPES = {"Organization", "LocalBusiness", "ProfessionalService", "Corporation", "Store",
             "Restaurant", "MedicalBusiness", "LegalService", "RealEstateAgent"}
ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "TechArticle"}


def _walk(node, out):
    """Flatten @graph / nested lists into a flat list of entity dicts."""
    if isinstance(node, list):
        for item in node:
            _walk(item, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _walk(node["@graph"], out)
        if "@type" in node:
            out.append(node)


def _types(entity) -> list[str]:
    t = entity.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def extract_jsonld(soup) -> dict:
    """Return {'types': [...], 'errors': n, 'blocks': n, 'entities': [dict, ...]}."""
    types, entities, errors, blocks = [], [], 0, 0
    for tag in soup.find_all("script", attrs={"type": lambda v: v and "ld+json" in v.lower()}):
        blocks += 1
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            errors += 1
            continue
        try:
            data = json.loads(raw, strict=False)
        except (ValueError, RecursionError):
            errors += 1
            continue
        flat: list = []
        _walk(data, flat)
        for ent in flat:
            entities.append(ent)
            for t in _types(ent):
                if t not in types:
                    types.append(t)
    return {"types": types, "errors": errors, "blocks": blocks, "entities": entities}


def entity_info(entities) -> dict:
    """Pull the identity-related fields we can observe in schema (name, contact, address, author, sameAs)."""
    info = {"org_names": [], "has_contact": False, "has_address": False,
            "has_author": False, "same_as": 0, "has_org": False, "has_website": False}
    for ent in entities:
        ts = set(_types(ent))
        if ts & ORG_TYPES:
            info["has_org"] = True
            name = ent.get("name")
            if isinstance(name, str) and name.strip():
                info["org_names"].append(name.strip())
            if ent.get("telephone") or ent.get("email") or ent.get("contactPoint"):
                info["has_contact"] = True
            if ent.get("address"):
                info["has_address"] = True
            same = ent.get("sameAs")
            if isinstance(same, list):
                info["same_as"] += len(same)
            elif isinstance(same, str):
                info["same_as"] += 1
        if "WebSite" in ts:
            info["has_website"] = True
        if ts & ARTICLE_TYPES and ent.get("author"):
            info["has_author"] = True
        if "Person" in ts:
            info["has_author"] = info["has_author"] or False
    return info


def check(pages) -> list[Issue]:
    """Issues about structured-data presence and validity (shown under AI Search Readiness)."""
    ok = [p for p in pages if p.analysable]
    if not ok:
        return []
    issues = []
    without = [p for p in ok if not p.schema_types]
    broken = [p for p in ok if p.schema_errors]
    if len(without) == len(ok):
        issues.append(Issue(
            id="schema_none", severity="MEDIUM", categories=["ai"],
            title="No structured data detected",
            found=f"None of the {plural(len(ok), 'crawled page')} contain readable JSON-LD structured data.",
            why="Structured data gives search engines and AI systems an explicit, machine-readable description of the "
                "organisation and page content. It does not directly improve rankings, but it can reduce ambiguity.",
            action="Consider adding JSON-LD for the business (Organization or LocalBusiness) and WebSite, plus "
                   "page-appropriate types such as BreadcrumbList, Article, Product or FAQPage.",
            rec="Add relevant structured data (Organization/LocalBusiness, WebSite, BreadcrumbList)",
            urls=[p.final_url for p in without], count=len(without)))
    elif without:
        issues.append(Issue(
            id="schema_partial", severity="LOW", categories=["ai"],
            title="Some pages have no structured data",
            found=f"{plural(len(without), 'crawled page')} of {len(ok)} have no JSON-LD.",
            why="Consistent structured data can help machines interpret the type and purpose of each page. "
                "Not every page type needs it.",
            action="Review which of these pages would benefit from relevant markup (for example Article, Product, "
                   "Service or BreadcrumbList) and add it where it accurately describes the page.",
            rec=f"Review structured data on {plural(len(without), 'page')} without markup",
            urls=[p.final_url for p in without], count=len(without)))
    if broken:
        issues.append(Issue(
            id="schema_errors", severity="MEDIUM", categories=["ai"],
            title="Malformed JSON-LD found",
            found=f"{plural(len(broken), 'page')} contain JSON-LD that could not be parsed.",
            why="Markup that cannot be parsed is ignored by consumers of structured data.",
            action="Validate the JSON-LD (for example with Google's Rich Results Test or schema.org validator) "
                   "and correct syntax errors.",
            rec=f"Fix malformed JSON-LD on {plural(len(broken), 'page')}",
            urls=[p.final_url for p in broken], count=len(broken)))
    return issues

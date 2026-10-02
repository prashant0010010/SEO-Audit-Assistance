"""Audit pipeline: crawl -> technical -> content -> schema -> AI readiness -> scoring."""
from __future__ import annotations

from datetime import datetime

from auditor import content, crawler, geo, schema, scoring, technical
from auditor.models import AuditResult, Issue
from utils.helpers import FRIENDLY_ERRORS, host_key
from utils.http import Fetcher

STEPS = [
    "Crawling website",
    "Checking technical SEO",
    "Checking content",
    "Checking structured data",
    "Checking AI-search readiness",
    "Building recommendations",
    "Preparing report",
]


def run_audit(url: str, client_name: str = "", max_pages: int = 10, progress=None, fetcher: Fetcher | None = None):
    """Run a full audit. `progress(step_index, label, detail='')` is optional and purely informational."""
    def tick(i: int, detail: str = "") -> None:
        if progress:
            progress(i, STEPS[i], detail)

    domain = host_key(url)
    result = AuditResult(client_name=client_name.strip(), start_url=url, domain=domain,
                         audit_date=datetime.now().strftime("%d %B %Y"))

    # 1. crawl
    tick(0)
    pages, site = crawler.crawl(
        url, max_pages, fetcher=fetcher,
        progress=lambda done, total, u: tick(0, f"{done}/{total}  {u}"))
    result.pages, result.site = pages, site
    home = pages[0]

    if not home.analysable:
        reason = home.error or (f"The homepage returned HTTP {home.status}." if home.status else
                                FRIENDLY_ERRORS["connection"])
        if home.status == 403:
            reason += " The site may block automated tools; try a different network or request access."
        result.reachable = False
        result.fatal_message = reason
        result.issues = [Issue(
            id="unreachable_site", severity="CRITICAL", categories=["technical"],
            title="Site cannot be reached",
            found=reason,
            why="If the site cannot be retrieved, neither users nor search engines can access any content.",
            action="Confirm the URL is correct and the site is online, then check hosting, DNS, SSL and any "
                   "firewall or bot-protection rules.",
            rec="Restore access to the website", urls=[url], count=1)]
        result.scores = {"technical": 0, "content": 0, "ai": 0, "overall": 0}
        result.ai_label = scoring.ai_label(0)
        result.recommendations = scoring.build_recommendations(result)
        result.summary = f"The audit could not be completed. {reason}"
        return result

    # 2. technical
    tick(1)
    tech_c, tech_i, broken = technical.check(pages, site)
    result.broken_links = broken

    # 3. content
    tick(2)
    cont_c, cont_i = content.check(pages)

    # 4. structured data
    tick(3)
    schema_i = schema.check(pages)
    for p in pages:
        if p.analysable and not p.schema_types:
            p.page_flags.append("No structured data")
        if p.schema_errors:
            p.page_flags.append("Malformed JSON-LD")

    # 5. AI readiness
    tick(4)
    ai_c, ai_i, signals = geo.check(pages, site, client_name, domain)
    result.ai_signals = signals

    # 6. scoring + recommendations
    tick(5)
    result.components = {"technical": tech_c, "content": cont_c, "ai": ai_c}
    merged: dict[str, Issue] = {}
    for issue in tech_i + cont_i + schema_i + ai_i:
        merged.setdefault(issue.id, issue)
    result.issues = scoring.sort_issues(list(merged.values()))
    scoring.build_scores(result)
    result.recommendations = scoring.build_recommendations(result)
    result.summary = scoring.build_summary(result)
    result.site.notes = result.site.notes[:8]
    tick(6)   # the caller builds the PDF at this step
    return result

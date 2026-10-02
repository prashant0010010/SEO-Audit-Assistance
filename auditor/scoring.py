"""Transparent scoring, issue prioritisation and recommendations.

Each category is a list of Components with fixed maximum points. A category score is
sum(earned) / sum(max of applicable components) * 100, so 'not applicable' items never penalise a site.
"""
from __future__ import annotations

import config
from auditor.models import SEVERITY_RANK, AuditResult, Component, Issue
from utils.helpers import plural

CATEGORY_NAMES = {"technical": "Technical SEO", "content": "Content Signals", "ai": "AI Search Readiness"}


def category_score(components: list[Component]) -> int:
    applicable = [c for c in components if c.applicable]
    total = sum(c.max_points for c in applicable)
    if not total:
        return 0
    return round(100 * sum(c.earned for c in applicable) / total)


def ai_label(score: int) -> str:
    return "Strong" if score >= 75 else ("Moderate" if score >= 50 else "Needs Attention")


def score_band(score: int) -> str:
    return "Good" if score >= 80 else ("Fair" if score >= 60 else "Needs work")


def sort_issues(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (SEVERITY_RANK[i.severity], -i.count, i.title))


def build_scores(result: AuditResult) -> None:
    for cat, comps in result.components.items():
        result.scores[cat] = category_score(comps)
    w = config.OVERALL_WEIGHTS
    result.scores["overall"] = round(sum(result.scores[k] * w[k] for k in w))
    result.ai_label = ai_label(result.scores["ai"])


def build_recommendations(result: AuditResult, limit: int = 8) -> list[str]:
    recs, seen = [], set()
    for issue in sort_issues(result.issues):
        if issue.rec not in seen:
            seen.add(issue.rec)
            recs.append(issue.rec)
    return recs[:limit]


def build_summary(result: AuditResult) -> str:
    ok = [p for p in result.pages if p.analysable]
    sev = {s: sum(1 for i in result.issues if i.severity == s) for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    s = result.scores
    parts = [
        f"We reviewed {plural(len(ok), 'page')} of {result.domain} and found "
        f"{plural(len(result.issues), 'item')} for review "
        f"({sev['CRITICAL']} critical, {sev['HIGH']} high, {sev['MEDIUM']} medium, {sev['LOW']} low).",
        f"The overall audit score is {s['overall']}/100 (technical {s['technical']}, content {s['content']}, "
        f"AI search readiness {s['ai']} \u2013 {result.ai_label}).",
    ]
    top = sort_issues(result.issues)[:1]
    if top:
        parts.append(f"The highest-priority finding is: {top[0].title.lower()}.")
    else:
        parts.append("No priority issues were detected in the sampled pages.")
    parts.append("Scores are automated heuristics based on a limited crawl and are intended to support "
                 "professional review.")
    return " ".join(parts)


def method_table() -> list[tuple[str, str]]:
    """Static description of the weights, shown in the UI, PDF and README."""
    w = config.OVERALL_WEIGHTS
    return [
        ("Overall", f"Technical \u00d7 {w['technical']:.0%} + Content \u00d7 {w['content']:.0%} + "
                    f"AI Search \u00d7 {w['ai']:.0%}"),
        ("Category score", "Sum of points earned by each check \u00f7 sum of points available, \u00d7 100. "
                           "Checks that do not apply to the site are excluded, not scored as failures."),
        ("Per-check points", "Most checks award points in proportion to the share of crawled pages that pass."),
    ]

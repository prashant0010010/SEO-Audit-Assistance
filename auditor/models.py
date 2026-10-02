"""Plain dataclasses shared across the audit engine."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass
class PageResult:
    url: str                               # URL as requested
    depth: int = 0
    discovered_via: str = "link"           # start | link | sitemap
    status: int = 0                        # 0 = no HTTP response
    final_url: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    error_kind: str = ""
    error: str = ""
    content_type: str = ""
    is_html: bool = False
    elapsed: float = 0.0

    # Metadata / structure
    title: str = ""
    meta_description: str = ""
    h1s: list[str] = field(default_factory=list)
    h2_count: int = 0
    h3_count: int = 0
    canonical: str = ""
    canonical_elsewhere: bool = False
    robots_meta: str = ""
    x_robots: str = ""
    noindex: bool = False
    nofollow: bool = False
    lang: str = ""

    # Links / images
    internal_links: list[str] = field(default_factory=list)   # unique absolute URLs
    external_links: list[str] = field(default_factory=list)   # unique absolute URLs
    images_total: int = 0
    images_missing_alt: int = 0
    images_empty_alt: int = 0
    mixed_content: int = 0
    inbound_links: int = 0

    # Content
    word_count: int = 0

    # Structured data
    schema_types: list[str] = field(default_factory=list)
    schema_errors: int = 0
    schema_blocks: int = 0

    # Observable AI-search signals (per page)
    signals: dict = field(default_factory=dict)

    # Filled by the checks
    page_flags: list[str] = field(default_factory=list)

    @property
    def is_https(self) -> bool:
        return (self.final_url or self.url).startswith("https://")

    @property
    def redirected(self) -> bool:
        return bool(self.redirect_chain)

    @property
    def analysable(self) -> bool:
        """A page we retrieved successfully as HTML and parsed."""
        return self.status == 200 and self.is_html and not self.error_kind

    @property
    def url_length(self) -> int:
        return len(self.final_url or self.url)


@dataclass
class SiteInfo:
    origin: str = ""
    host: str = ""
    robots_url: str = ""
    robots_status: int = 0
    robots_exists: bool = False
    robots_allows_all_crawl: bool = True
    robots_sitemaps: list[str] = field(default_factory=list)
    robots_blocked_urls: list[str] = field(default_factory=list)
    sitemap_url: str = ""
    sitemap_exists: bool = False
    sitemap_url_count: int = 0
    sitemap_referenced_in_robots: bool = False
    sitemap_urls: list[str] = field(default_factory=list)
    link_sources: dict = field(default_factory=dict)       # norm target -> set(source urls)
    checked_links: dict = field(default_factory=dict)      # url -> status (HEAD checks of extra links)
    unchecked_internal_links: int = 0
    notes: list[str] = field(default_factory=list)         # friendly crawl messages


@dataclass
class Issue:
    id: str
    severity: str
    categories: list[str]                   # technical / content / ai
    title: str
    found: str
    why: str
    action: str
    rec: str                                # short imperative used in the Recommendations list
    urls: list[str] = field(default_factory=list)
    count: int = 0

    _VERBS = {"have": "has", "are": "is", "were": "was", "set": "sets", "use": "uses", "show": "shows",
              "contain": "contains", "link": "links", "redirect": "redirects", "exceed": "exceeds",
              "carry": "carries", "describe": "describes", "reference": "references", "point": "points",
              "return": "returns", "share": "shares", "lack": "lacks"}

    def __post_init__(self):
        """Singular agreement for generated sentences such as '1 page have ...' -> '1 page has ...'."""
        if self.found.startswith("1 "):
            m = re.search(r"\b(" + "|".join(self._VERBS) + r")\b", self.found)
            if m:
                self.found = self.found[:m.start()] + self._VERBS[m.group(1)] + self.found[m.end():]


@dataclass
class Component:
    name: str
    max_points: float
    earned: float = 0.0
    detail: str = ""
    applicable: bool = True


@dataclass
class AuditResult:
    client_name: str
    start_url: str
    domain: str
    audit_date: str
    pages: list[PageResult] = field(default_factory=list)
    site: SiteInfo = field(default_factory=SiteInfo)
    issues: list[Issue] = field(default_factory=list)
    components: dict = field(default_factory=dict)         # category -> list[Component]
    scores: dict = field(default_factory=dict)             # technical/content/ai/overall
    ai_label: str = ""
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""
    reachable: bool = True
    fatal_message: str = ""
    broken_links: list[tuple] = field(default_factory=list)   # (source, target, status)
    ai_signals: list[tuple] = field(default_factory=list)     # (signal, observed, detail)

    def issues_for(self, category: str) -> list[Issue]:
        return [i for i in self.issues if category in i.categories]

"""Central configuration. Values can be overridden with environment variables (see .env.example)."""
import os

APP_NAME = "Client SEO Audit Assistant"
VERSION = "1.0.0"

USER_AGENT = os.getenv(
    "AUDIT_USER_AGENT",
    "ClientSEOAuditAssistant/1.0 (+portfolio project; polite single-site audit)",
)

# Crawl behaviour
PAGE_LIMIT_OPTIONS = (5, 10, 20)
DEFAULT_PAGE_LIMIT = 10
CRAWL_DELAY_SECONDS = float(os.getenv("AUDIT_CRAWL_DELAY", "0.5"))
CONNECT_TIMEOUT = 6
READ_TIMEOUT = 12
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2_000_000          # body read cap per page
LINK_CHECK_LIMIT = 15                    # extra internal links verified with HEAD requests
SITEMAP_URL_SAMPLE = 5000                # max <loc> entries read from a sitemap

# Safety: refuse localhost / private-network targets unless explicitly allowed (local testing only).
ALLOW_PRIVATE_HOSTS = os.getenv("AUDIT_ALLOW_PRIVATE_HOSTS", "0") == "1"

# Content thresholds (heuristics, not rules)
TITLE_MIN, TITLE_MAX = 20, 65
DESC_MIN, DESC_MAX = 70, 165
THIN_WORDS = 150
VERY_THIN_WORDS = 50
GOOD_WORDS = 300
MIN_INTERNAL_LINKS = 3
LONG_URL = 115

# Scoring weights for the overall score (must sum to 1.0)
OVERALL_WEIGHTS = {"technical": 0.40, "content": 0.30, "ai": 0.30}

HEURISTIC_LABEL = "Audit heuristic \u2014 not a Google ranking score."
DISCLAIMER = (
    "Audit results are automated heuristics intended to support professional review. "
    "They are not search-engine rankings or guarantees."
)

# Report styling
ACCENT = "#1F5C5C"
INK = "#1A1A1A"
PAPER = "#FAF8F4"

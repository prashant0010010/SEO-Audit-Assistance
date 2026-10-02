# Client SEO Audit Assistant

Technical SEO, content and AI-search readiness checks for public websites, with a client-ready PDF report.

Built with Python and Streamlit. No database, no accounts, no paid APIs.

## Why I built this

I built this project to explore how Python automation can reduce repetitive technical SEO auditing work and combine traditional search optimisation with emerging AI-search considerations.

It is a portfolio tool, not a replacement for an SEO professional: it automates the repetitive checks so that analyst time goes into interpretation and client work.

## Features

- **Careful same-site crawler**: 5, 10 or 20 pages, shared `requests.Session`, timeouts, delay between requests, robots.txt respected, redirect and loop handling, sitemap used to find pages the links miss.
- **Technical SEO**: status codes, redirects, HTTPS and mixed-content indicators, titles, meta descriptions, H1s, canonicals, noindex/nofollow (meta and X-Robots-Tag), broken internal links, orphan-like pages, image alt text, robots.txt and sitemap checks.
- **Content signals**: word count, title and description length, headings, internal/external links, image counts. Wording is "review recommended", never "bad page".
- **Structured data**: JSON-LD extraction (Organization, LocalBusiness, Product, Article, FAQPage, BreadcrumbList, WebSite, Person and more); malformed JSON-LD is reported, never fatal.
- **AI Search Readiness**: observable signals (identity, About/contact, schema, headings, FAQ-style content, attribution, internal linking) rated Strong / Moderate / Needs Attention. An internal heuristic, not a ranking prediction.
- **Prioritised issues**: CRITICAL / HIGH / MEDIUM / LOW, each with *what we found*, *why it matters* and *recommended action*.
- **Outputs**: Streamlit dashboard, CSV of page-level data, and a ReportLab PDF (cover, executive summary, technical, content, AI search, appendix).

## Tech stack

Python 3.11+, Streamlit, Requests, BeautifulSoup4 (+ lxml), pandas, ReportLab. Standard library for everything else (`urllib`, `robotparser`, `json`, `dataclasses`).

## Installation

```bash
git clone <your-repo-url> seo-audit-assistant
cd seo-audit-assistant
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## How to run

```bash
streamlit run app.py
```

Open http://localhost:8501.

Run the offline tests (they use a local fake website, no internet needed):

```bash
python -m tests.test_engine
python -m tests.test_pdf
```

## Example workflow

1. Enter the client's URL (and optionally the business name, which improves the brand-identity check).
2. Choose how many pages to crawl and click **Run Audit**.
3. Read the four scores and the top 5 priority issues.
4. Work through the tabs: Overview, Technical, Content, AI Search, Pages, Recommendations.
5. Download the PDF for the client and the CSV for further analysis.

## Scoring methodology

*Audit heuristic: not a Google ranking score.*

Every check has fixed maximum points. Most award points in proportion to the share of crawled pages that pass. A category score is `points earned / points available x 100`. Checks that do not apply (for example, author information on a site with no articles) are excluded rather than counted as failures.

**Overall = Technical x 40% + Content x 30% + AI Search Readiness x 30%**

| Technical SEO (100) | Points | Content Signals (100) | Points |
|---|---|---|---|
| Page availability | 20 | Title quality (length) | 20 |
| Indexability (noindex) | 15 | Meta description quality (length) | 20 |
| Titles and descriptions: present + unique | 15 | H1 present | 10 |
| Canonical present / not pointing elsewhere | 7 + 3 | Subheadings on text-rich pages | 10 |
| H1 heading | 10 | Content depth signals | 25 |
| Internal links not broken / no orphan-like pages | 6 + 4 | Internal linking | 15 |
| robots.txt / sitemap / sitemap in robots | 4 + 4 + 2 | | |
| HTTPS / no mixed-content indicators | 3 + 2 | | |
| Images with alt attribute | 5 | | |

| AI Search Readiness (100, internal heuristic) | Points |
|---|---|
| Structured data coverage / Organisation + WebSite markup | 15 + 10 |
| Business name on homepage / org name in schema / name in titles | 8 + 7 + 5 |
| About page / Contact page / contact details visible | 5 + 5 + 5 |
| Heading structure / descriptive content / FAQ-style content | 10 + 5 + 5 |
| Author information / source references (only if article-like pages exist) | 5 + 5 |
| Internal link coverage / pages reachable via internal links | 5 + 5 |

AI Search Readiness bands: **Strong** 75+, **Moderate** 50-74, **Needs Attention** below 50. These bands and weights are my own judgement, not a validated metric, and the score does not predict whether ChatGPT, Google AI Overviews, Perplexity or any other system will rank or cite a site. FAQ-style content is scored because it often helps, but it is not appropriate for every site.

The UI and PDF show the points awarded to every individual check so the result can be challenged and adjusted.

## Limitations

- The crawl is a **sample** (max 20 pages). Findings describe the pages reviewed, not the whole site.
- Pages are fetched as raw HTML. **JavaScript-rendered content is not executed**, so client-side rendered sites can look thin.
- Mixed content is detected from HTML source only; there is no Core Web Vitals, rendering, backlink, keyword or ranking data.
- Orphan-like detection only sees links from crawled pages.
- Broken-link verification checks up to 15 extra internal URLs to keep audits fast.
- Word-count and length thresholds are conventional rules of thumb and are shown as "review recommended" prompts.
- Sites that block automated tools (403, bot protection) cannot be audited.

## Responsible use

Audit only websites you own or have permission to review. The tool only reads public pages, identifies itself with a User-Agent, respects robots.txt, uses a delay between requests and a hard page cap. It does not log in, bypass CAPTCHAs, scan ports or test for vulnerabilities, and refuses localhost/private-network addresses. (Basic guard only: it does not defend against DNS rebinding.)


## Future improvements

1. **v1.1: Agency workflow**: audit multiple URLs from a CSV, branded PDF (logo and colours), before/after comparison between two audit dates.
2. **v1.2: Deeper checks**: optional rendered-HTML fetch for JavaScript sites, Core Web Vitals via the public PageSpeed API, hreflang and pagination checks, local-SEO checks (NAP consistency, LocalBusiness schema validation).
3. **v2.0: Data integrations**: Google Search Console and GA4 import to prioritise issues by real traffic and impressions, with an optional LLM-written executive summary behind a clear review step.

## Project structure

```
app.py                  Streamlit interface
config.py               thresholds, weights, timeouts
auditor/                crawler, technical, content, schema, geo, scoring, models (pipeline in __init__.py)
reports/pdf_report.py   ReportLab PDF
utils/                  http.py (polite Session wrapper), helpers.py
tests/                  offline fake site + engine, PDF and app smoke tests
```

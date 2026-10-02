"""Client-ready PDF report built with ReportLab (Platypus). No external fonts or images required."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

import config
from auditor import scoring
from auditor.models import AuditResult, Issue
from utils.helpers import short_url

ACCENT = colors.HexColor(config.ACCENT)
INK = colors.HexColor(config.INK)
MUTED = colors.HexColor("#6B6B66")
RULE = colors.HexColor("#CFCBC1")
SEV_COLOR = {"CRITICAL": "#8B1A1A", "HIGH": "#B4530A", "MEDIUM": "#8A6D00", "LOW": "#5B6770"}

W, H = A4
MARGIN = 20 * mm
CONTENT_W = W - 2 * MARGIN


def _styles():
    base = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT)
    return {
        "kicker": ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT,
                                 leading=12, spaceAfter=6, charSpace=1.5),
        "title": ParagraphStyle("title", fontName="Times-Bold", fontSize=30, leading=34, textColor=INK,
                                spaceAfter=6),
        "h1": ParagraphStyle("h1", fontName="Times-Bold", fontSize=20, leading=24, textColor=INK, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK,
                             spaceBefore=12, spaceAfter=5, keepWithNext=1),
        "body": ParagraphStyle("body", fontSize=9.5, leading=14, **base),
        "small": ParagraphStyle("small", fontSize=8.2, leading=11, **base),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=8.2, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontSize=7.8, leading=10, **base),
        "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=7.8, leading=10, textColor=INK),
        "score_big": ParagraphStyle("score_big", fontName="Times-Bold", fontSize=54, leading=56, textColor=ACCENT),
        "score_mid": ParagraphStyle("score_mid", fontName="Times-Bold", fontSize=22, leading=24, textColor=INK),
    }


def _p(text, style) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _table(rows, widths, st, header=True, repeat=True) -> Table:
    data = []
    for r, row in enumerate(rows):
        style = st["cellb"] if (header and r == 0) else st["cell"]
        data.append([c if not isinstance(c, (str, int, float)) else _p(c, style) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1 if (header and repeat) else 0)
    cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if header:
        cmds += [("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT)]
    t.setStyle(TableStyle(cmds))
    return t


def _issue_block(issue: Issue, st) -> KeepTogether:
    sev = ParagraphStyle("sev", parent=st["cellb"], textColor=colors.HexColor(SEV_COLOR[issue.severity]),
                         fontSize=7.8, charSpace=0.8)
    rows = [
        [Paragraph(escape(issue.severity), sev), Paragraph(f"<b>{escape(issue.title)}</b>", st["small"])],
        [_p("FOUND", st["muted"]), _p(issue.found, st["small"])],
        [_p("WHY IT MATTERS", st["muted"]), _p(issue.why, st["small"])],
        [_p("RECOMMENDED ACTION", st["muted"]), _p(issue.action, st["small"])],
    ]
    if issue.urls:
        shown = ", ".join(short_url(u, 48) for u in issue.urls[:3]) + (f" (+{len(issue.urls) - 3} more)"
                                                                         if len(issue.urls) > 3 else "")
        rows.append([_p("EXAMPLES", st["muted"]), _p(shown, st["muted"])])
    t = Table(rows, colWidths=[32 * mm, CONTENT_W - 32 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([t, Spacer(1, 7)])


def _components_table(comps, st):
    rows = [["Check", "Points", "Observation"]]
    for c in comps:
        pts = f"{c.earned:g} / {c.max_points:g}" if c.applicable else "n/a"
        rows.append([c.name, pts, c.detail])
    return _table(rows, [50 * mm, 20 * mm, CONTENT_W - 70 * mm], st)


def _score_header(label, score, st, extra=""):
    t = Table([[Paragraph(f"{score}", st["score_mid"]),
                [Paragraph(f"<b>{escape(label)}</b> \u2013 {scoring.score_band(score) if not extra else escape(extra)}",
                           st["body"]),
                 Paragraph(escape(config.HEURISTIC_LABEL), st["muted"])]]],
              colWidths=[24 * mm, CONTENT_W - 24 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.4, RULE), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN, 14 * mm, W - MARGIN, 14 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 10 * mm, config.HEURISTIC_LABEL)
    canvas.drawRightString(W - MARGIN, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _issues_section(result, cat, st, limit=6):
    out = []
    issues = scoring.sort_issues(result.issues_for(cat))
    if not issues:
        out.append(_p("No issues were detected for this area in the sampled pages.", st["body"]))
    for i in issues[:limit]:
        out.append(_issue_block(i, st))
    if len(issues) > limit:
        out.append(_p(f"{len(issues) - limit} further lower-priority item(s) are listed in the web app.", st["muted"]))
    return out


def build_pdf(result: AuditResult, path: str | None = None) -> bytes:
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=18 * mm,
                            bottomMargin=20 * mm, title=f"SEO Audit \u2013 {result.client_name or result.domain}",
                            author=config.APP_NAME)
    s = result.scores
    name = result.client_name or result.domain
    ok = [p for p in result.pages if p.analysable]
    story = []

    # ---------------- PAGE 1: cover
    story += [Spacer(1, 30 * mm), _p("CLIENT SEO AUDIT", st["kicker"]), _p(name, st["title"]),
              _p(f"{result.domain}  \u00b7  {result.audit_date}", st["body"]), Spacer(1, 14 * mm),
              Paragraph(f"{s['overall']}<font size=16 color='#6B6B66'> / 100</font>", st["score_big"]),
              _p("Overall audit score", st["muted"]), Spacer(1, 8 * mm)]
    cards = Table([[_p("TECHNICAL SEO", st["muted"]), _p("CONTENT SIGNALS", st["muted"]),
                    _p("AI SEARCH READINESS", st["muted"])],
                   [_p(f"{s['technical']}/100", st["score_mid"]), _p(f"{s['content']}/100", st["score_mid"]),
                    _p(f"{s['ai']}/100  {result.ai_label}", st["score_mid"])]],
                  colWidths=[CONTENT_W / 3] * 3)
    cards.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, ACCENT), ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [cards, Spacer(1, 10 * mm), _p(result.summary, st["body"]), Spacer(1, 12 * mm),
              _p(config.HEURISTIC_LABEL, st["muted"]), Spacer(1, 2), _p(config.DISCLAIMER, st["muted"]),
              PageBreak()]

    # ---------------- PAGE 2: executive summary
    story += [_p("Executive summary", st["h1"]), _p("Top findings", st["h2"])]
    top = scoring.sort_issues(result.issues)[:5]
    if top:
        rows = [["Priority", "Finding", "Affected"]]
        for i in top:
            rows.append([Paragraph(f"<font color='{SEV_COLOR[i.severity]}'><b>{i.severity}</b></font>", st["cell"]),
                         _p(i.title + " \u2013 " + i.found, st["cell"]), _p(i.count, st["cell"])])
        story.append(_table(rows, [24 * mm, CONTENT_W - 40 * mm, 16 * mm], st))
    else:
        story.append(_p("No priority issues were detected in the sampled pages.", st["body"]))
    story.append(_p("Top recommendations", st["h2"]))
    for n, rec in enumerate(result.recommendations[:5], 1):
        story.append(_p(f"{n}.  {rec}", st["body"]))
    story += [Spacer(1, 6 * mm), _p("Audit scope", st["h2"]),
              _p(f"{len(result.pages)} URLs crawled ({len(ok)} analysed as HTML pages). robots.txt: "
                 f"{'found' if result.site.robots_exists else 'not found'}. XML sitemap: "
                 f"{'found' if result.site.sitemap_exists else 'not found'}. The crawl is a limited sample of the "
                 "site, so findings describe the pages reviewed rather than every URL.", st["body"]),
              PageBreak()]

    # ---------------- PAGE 3: technical
    story += [_p("Technical SEO", st["h1"]), _score_header("Technical SEO score", s["technical"], st),
              _p("Score breakdown", st["h2"]), _components_table(result.components["technical"], st),
              _p("Issues", st["h2"])] + _issues_section(result, "technical", st)
    rows = [["URL", "Status", "Canonical", "Robots", "H1s", "Alt gaps"]]
    for p in result.pages[:12]:
        rows.append([short_url(p.final_url or p.url, 52), p.status or "error",
                     ("self" if p.canonical and not p.canonical_elsewhere else ("other" if p.canonical else "none"))
                     if p.analysable else "-",
                     ("noindex" if p.noindex else "index") if p.analysable else "-",
                     len(p.h1s) if p.analysable else "-", p.images_missing_alt if p.analysable else "-"])
    story += [_p("Page-level findings", st["h2"]),
              _table(rows, [CONTENT_W - 100 * mm, 14 * mm, 22 * mm, 20 * mm, 14 * mm, 30 * mm], st),
              _p("First 12 URLs shown; all pages are listed in the appendix.", st["muted"]), PageBreak()]

    # ---------------- PAGE 4: content
    story += [_p("Content signals", st["h1"]), _score_header("Content score", s["content"], st),
              _p("Score breakdown", st["h2"]), _components_table(result.components["content"], st),
              _p("Issues", st["h2"])] + _issues_section(result, "content", st)
    rows = [["URL", "Words", "Title chars", "Desc chars", "H2", "Int. links", "Ext. links", "Images"]]
    for p in ok[:12]:
        rows.append([short_url(p.final_url, 44), p.word_count, len(p.title), len(p.meta_description),
                     p.h2_count, len(p.internal_links), len(p.external_links), p.images_total])
    story += [_p("Page-level findings", st["h2"]),
              _table(rows, [CONTENT_W - 112 * mm] + [14 * mm] * 8, st),
              _p("Word count is a signal for review, not a verdict on page quality.", st["muted"]), PageBreak()]

    # ---------------- PAGE 5: AI search readiness
    story += [_p("AI search readiness", st["h1"]),
              _score_header("AI search readiness (internal heuristic)", s["ai"], st, extra=result.ai_label),
              _p("This section reviews observable signals that may help content be understood and attributed. It "
                 "does not predict whether any AI system or search engine will rank, retrieve or cite the site.",
                 st["body"]),
              _p("Observable signals", st["h2"])]
    rows = [["Signal", "Observed", "Detail"]] + [[a, b, c] for a, b, c in result.ai_signals]
    story += [_table(rows, [48 * mm, 20 * mm, CONTENT_W - 68 * mm], st), _p("Score breakdown", st["h2"]),
              _components_table(result.components["ai"], st), _p("Recommendations", st["h2"])]
    story += _issues_section(result, "ai", st)
    story.append(PageBreak())

    # ---------------- APPENDIX
    story += [_p("Appendix", st["h1"]), _p("Scoring methodology", st["h2"])]
    story.append(_table([["Item", "Method"]] + [[a, b] for a, b in scoring.method_table()],
                        [32 * mm, CONTENT_W - 32 * mm], st))
    story += [Spacer(1, 3), _p(config.HEURISTIC_LABEL + " The AI search readiness score is an internal heuristic, "
                               "not a scientifically validated ranking metric.", st["muted"]),
              _p("Page-level audit table", st["h2"])]
    rows = [["URL", "Status", "Words", "Title", "Desc", "H1", "Canon.", "Schema", "Flags"]]
    for p in result.pages:
        rows.append([short_url(p.final_url or p.url, 40), p.status or "err",
                     p.word_count if p.analysable else "-", "Y" if p.title else "N", "Y" if p.meta_description else "N",
                     len(p.h1s), "Y" if p.canonical else "N", "Y" if p.schema_types else "N", len(p.page_flags)])
    story.append(_table(rows, [CONTENT_W - 106 * mm, 13 * mm, 13 * mm, 11 * mm, 11 * mm, 9 * mm, 14 * mm, 15 * mm, 20 * mm],
                        st))
    if result.site.notes:
        story += [_p("Crawl notes", st["h2"])] + [_p("\u2022  " + n, st["small"]) for n in result.site.notes]
    story += [Spacer(1, 6 * mm), _p(config.DISCLAIMER, st["muted"])]

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    data = buf.getvalue()
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
    return data

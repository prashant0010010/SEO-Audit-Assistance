"""Client SEO Audit Assistant - Streamlit interface.  Run with:  streamlit run app.py"""
from __future__ import annotations

import os
import re
from html import escape

import pandas as pd
import streamlit as st

import config
from auditor import STEPS, run_audit, scoring
from auditor.models import AuditResult, Issue
from reports.pdf_report import build_pdf
from utils.helpers import pages_to_dataframe, short_url, validate_url

st.set_page_config(page_title=config.APP_NAME, page_icon=None, layout="wide")

SEV_COLOR = {"CRITICAL": "#8B1A1A", "HIGH": "#B4530A", "MEDIUM": "#8A6D00", "LOW": "#5B6770"}

CSS = f"""
<style>
#MainMenu, footer {{visibility: hidden;}}
.block-container {{padding-top: 2.4rem; max-width: 1100px;}}
h1, h2, h3, .serif {{font-family: Georgia, 'Times New Roman', serif !important; color: {config.INK};
  font-weight: 700; letter-spacing: -0.01em;}}
.kicker {{font-size: 0.72rem; letter-spacing: 0.16em; font-weight: 700; color: {config.ACCENT};
  text-transform: uppercase; margin-bottom: 0.2rem;}}
.sub {{color: #5d5d58; margin-top: -0.4rem; margin-bottom: 1.2rem;}}
.card {{border: 1px solid #CFCBC1; border-top: 2px solid {config.ACCENT}; padding: 0.8rem 1rem 0.6rem;
  background: transparent;}}
.card .lbl {{font-size: 0.68rem; letter-spacing: 0.14em; color: #6B6B66; font-weight: 700;}}
.card .num {{font-family: Georgia, serif; font-size: 2.1rem; font-weight: 700; line-height: 1.15;
  color: {config.INK};}}
.card .num small {{font-size: 0.95rem; color: #6B6B66; font-weight: 400;}}
.card .note {{font-size: 0.78rem; color: #6B6B66;}}
.issue {{border-bottom: 1px solid #CFCBC1; padding: 0.7rem 0 0.8rem;}}
.issue .sev {{font-size: 0.7rem; letter-spacing: 0.12em; font-weight: 700;}}
.issue .ttl {{font-weight: 700; margin-left: 0.6rem;}}
.issue .row {{font-size: 0.88rem; margin-top: 0.3rem; line-height: 1.45;}}
.issue .row b {{font-size: 0.66rem; letter-spacing: 0.1em; color: #6B6B66; display: inline-block; min-width: 9.5rem;}}
.issue .ex {{font-size: 0.78rem; color: #6B6B66; margin-top: 0.3rem;}}
.muted {{color: #6B6B66; font-size: 0.82rem;}}
.rec {{border-left: 2px solid {config.ACCENT}; padding: 0.15rem 0 0.15rem 0.9rem; margin-bottom: 0.8rem;}}
.rec .p {{font-size: 0.68rem; letter-spacing: 0.12em; color: #6B6B66; font-weight: 700;}}
.banner {{border: 1px solid #CFCBC1; padding: 0.9rem 1.1rem; margin-bottom: 0.6rem;}}
.banner .big {{font-family: Georgia, serif; font-size: 1.5rem; font-weight: 700;}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def show_df(df: pd.DataFrame, **kwargs) -> None:
    """st.dataframe across Streamlit versions (width API changed in 1.50)."""
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kwargs)
    except TypeError:
        st.dataframe(df, hide_index=True, use_container_width=True, **kwargs)


def card(label: str, score: int, note: str = "") -> str:
    return (f"<div class='card'><div class='lbl'>{escape(label)}</div>"
            f"<div class='num'>{score}<small>/100</small></div><div class='note'>{escape(note) or '&nbsp;'}</div></div>")


def issue_html(i: Issue, examples: int = 4) -> str:
    ex = ""
    if i.urls:
        shown = ", ".join(escape(short_url(u, 56)) for u in i.urls[:examples])
        more = f" (+{len(i.urls) - examples} more)" if len(i.urls) > examples else ""
        ex = f"<div class='ex'>Examples: {shown}{more}</div>"
    return (f"<div class='issue'><span class='sev' style='color:{SEV_COLOR[i.severity]}'>{i.severity}</span>"
            f"<span class='ttl'>{escape(i.title)}</span>"
            f"<div class='row'><b>WHAT WE FOUND</b>{escape(i.found)}</div>"
            f"<div class='row'><b>WHY IT MATTERS</b>{escape(i.why)}</div>"
            f"<div class='row'><b>RECOMMENDED ACTION</b>{escape(i.action)}</div>{ex}</div>")


def render_issues(issues: list[Issue], empty: str = "No issues detected in the sampled pages.") -> None:
    if not issues:
        st.markdown(f"<div class='muted'>{escape(empty)}</div>", unsafe_allow_html=True)
    for i in issues:
        st.markdown(issue_html(i), unsafe_allow_html=True)


def components_df(comps) -> pd.DataFrame:
    return pd.DataFrame([{
        "Check": c.name,
        "Points": f"{c.earned:g} / {c.max_points:g}" if c.applicable else "n/a",
        "Observation": c.detail} for c in comps])


def heading(text: str) -> None:
    st.markdown(f"<h3 style='margin-top:1.4rem'>{escape(text)}</h3>", unsafe_allow_html=True)


# ------------------------------------------------------------------ landing
def landing() -> None:
    st.markdown("<div class='kicker'>Client SEO Audit Assistant</div>", unsafe_allow_html=True)
    st.markdown("<h1 style='margin-top:0'>CLIENT SEO AUDIT ASSISTANT</h1>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Technical SEO, content and AI-search readiness checks for public websites.</div>",
                unsafe_allow_html=True)
    left, _ = st.columns([3, 2])
    with left:
        with st.form("audit_form"):
            url = st.text_input("Website URL", placeholder="https://example.com")
            client = st.text_input("Client / Business Name", placeholder="Example Business")
            pages = st.selectbox("Pages to crawl", config.PAGE_LIMIT_OPTIONS,
                                 index=config.PAGE_LIMIT_OPTIONS.index(config.DEFAULT_PAGE_LIMIT))
            go = st.form_submit_button("Run Audit")
        st.markdown(f"<div class='muted'>{escape(config.DISCLAIMER)}</div>", unsafe_allow_html=True)
    if not go:
        return

    clean_url, err = validate_url(url)
    if err:
        st.error(err)
        return

    with st.status("Running audit", expanded=True) as status:
        bar = st.progress(0)
        detail = st.empty()
        seen = set()

        def on_progress(i: int, label: str, info: str = "") -> None:
            if i not in seen:
                seen.add(i)
                status.write(f"{i + 1}. {label}")
                status.update(label=f"{i + 1} of {len(STEPS)}: {label}")
                bar.progress(min((i + 1) / len(STEPS), 1.0))
            detail.caption(info[:110])

        try:
            result = run_audit(clean_url, client, int(pages), progress=on_progress)
            pdf = b""
            if result.reachable:
                try:
                    pdf = build_pdf(result)
                except Exception as exc:            # report problems must not hide the audit results
                    st.warning(f"The PDF report could not be generated ({type(exc).__name__}). "
                               "The on-screen results are still available.")
            status.update(label="Audit complete", state="complete", expanded=False)
        except Exception as exc:                    # last-resort guard: never show a stack trace to the user
            status.update(label="Audit stopped", state="error")
            st.error("Something unexpected went wrong while auditing this site "
                     f"({type(exc).__name__}). Please check the URL and try again.")
            return
    st.session_state["result"], st.session_state["pdf"] = result, pdf
    st.rerun()


# ------------------------------------------------------------------ results
def results(result: AuditResult, pdf: bytes) -> None:
    name = result.client_name or result.domain
    top, mid = st.columns([4, 1])
    with top:
        st.markdown("<div class='kicker'>Client SEO Audit</div>", unsafe_allow_html=True)
        st.markdown(f"<h1 style='margin-top:0'>{escape(name)}</h1>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub'>{escape(result.domain)} &nbsp;\u00b7&nbsp; {escape(result.audit_date)}</div>",
                    unsafe_allow_html=True)
    with mid:
        if st.button("New audit"):
            st.session_state.pop("result", None)
            st.session_state.pop("pdf", None)
            st.rerun()
        if pdf:
            fname = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "site"
            st.download_button("Download PDF", pdf, file_name=f"seo-audit-{fname}.pdf", mime="application/pdf")

    if not result.reachable:
        st.error(f"We couldn't audit this website. {result.fatal_message}")
        render_issues(result.issues)
        return

    s = result.scores
    c = st.columns(4)
    c[0].markdown(card("OVERALL", s["overall"], scoring.score_band(s["overall"])), unsafe_allow_html=True)
    c[1].markdown(card("TECHNICAL", s["technical"], scoring.score_band(s["technical"])), unsafe_allow_html=True)
    c[2].markdown(card("CONTENT", s["content"], scoring.score_band(s["content"])), unsafe_allow_html=True)
    c[3].markdown(card("AI SEARCH", s["ai"], result.ai_label), unsafe_allow_html=True)
    st.markdown(f"<div class='muted' style='margin-top:.4rem'>{escape(config.HEURISTIC_LABEL)}</div>",
                unsafe_allow_html=True)

    for note in result.site.notes[:3]:
        st.info(note)

    heading("Priority Issues")
    render_issues(scoring.sort_issues(result.issues)[:5], "No priority issues were detected.")

    t_over, t_tech, t_cont, t_ai, t_pages, t_rec = st.tabs(
        ["Overview", "Technical", "Content", "AI Search", "Pages", "Recommendations"])

    with t_over:
        st.write(result.summary)
        sev = pd.DataFrame([{"Priority": k, "Issues": sum(1 for i in result.issues if i.severity == k)}
                            for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW")])
        ok = [p for p in result.pages if p.analysable]
        a, b = st.columns(2)
        with a:
            heading("Issues by priority")
            show_df(sev)
        with b:
            heading("Crawl summary")
            show_df(pd.DataFrame([
                {"Item": "URLs crawled", "Value": len(result.pages)},
                {"Item": "Analysed as HTML pages", "Value": len(ok)},
                {"Item": "robots.txt", "Value": "Found" if result.site.robots_exists else "Not found"},
                {"Item": "XML sitemap", "Value": f"Found ({result.site.sitemap_url_count} URLs)"
                 if result.site.sitemap_exists else "Not found"},
                {"Item": "Internal links verified (extra)", "Value": len(result.site.checked_links)}]))
        heading("How the scores are calculated")
        show_df(pd.DataFrame(scoring.method_table(), columns=["Item", "Method"]))
        st.caption(config.HEURISTIC_LABEL + " Open the Technical, Content and AI Search tabs for the points "
                   "awarded to every individual check.")
        if len(result.site.notes) > 3:
            with st.expander("All crawl notes"):
                for n in result.site.notes:
                    st.write("\u2022 " + n)

    with t_tech:
        st.markdown(f"**Technical SEO score: {s['technical']}/100**")
        show_df(components_df(result.components["technical"]))
        heading("Issues")
        render_issues(result.issues_for("technical"))
        if result.broken_links:
            heading("Broken internal links")
            show_df(pd.DataFrame(result.broken_links, columns=["Linked from", "Broken URL", "Status"])
                    .astype({"Status": str}))

    with t_cont:
        st.markdown(f"**Content score: {s['content']}/100**")
        show_df(components_df(result.components["content"]))
        heading("Issues")
        render_issues(result.issues_for("content"))
        heading("Content signals by page")
        rows = [{"URL": p.final_url, "Words": p.word_count, "Title chars": len(p.title),
                 "Description chars": len(p.meta_description), "H1": len(p.h1s), "H2": p.h2_count,
                 "Internal links": len(p.internal_links), "External links": len(p.external_links),
                 "Images": p.images_total} for p in result.pages if p.analysable]
        show_df(pd.DataFrame(rows))
        st.caption("Word count is a signal for review, not a verdict on page quality.")

    with t_ai:
        st.markdown(f"<div class='banner'><div class='muted'>AI SEARCH READINESS</div>"
                    f"<div class='big'>{escape(result.ai_label)} &nbsp;<span class='muted'>{s['ai']}/100</span></div>"
                    "<div class='muted'>Internal heuristic based on observable signals. It is not a validated "
                    "ranking metric and does not predict whether any AI system will rank or cite this site."
                    "</div></div>", unsafe_allow_html=True)
        heading("Observable signals")
        show_df(pd.DataFrame(result.ai_signals, columns=["Signal", "Observed", "Detail"]))
        heading("Score breakdown")
        show_df(components_df(result.components["ai"]))
        heading("Issues and opportunities")
        render_issues(result.issues_for("ai"))

    with t_pages:
        df = pages_to_dataframe(result.pages)
        show_df(df)
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"),
                           file_name=f"pages-{result.domain}.csv", mime="text/csv")

    with t_rec:
        if not result.recommendations:
            st.write("No recommendations: no issues were detected in the sampled pages.")
        for n, rec in enumerate(result.recommendations, 1):
            st.markdown(f"<div class='rec'><div class='p'>PRIORITY {n}</div>{escape(rec)}</div>",
                        unsafe_allow_html=True)
        st.caption("Recommendations are generated from the findings above and ordered by priority and the number "
                   "of pages affected. Professional review is recommended before implementation.")

    st.markdown(f"<div class='muted' style='margin-top:2rem'>{escape(config.DISCLAIMER)}</div>",
                unsafe_allow_html=True)


# ------------------------------------------------------------------ entry
if "result" in st.session_state:
    results(st.session_state["result"], st.session_state.get("pdf", b""))
else:
    landing()

"""Smoke-tests app.py logic with a stub 'streamlit' (the real package is not needed for this check).
It exercises both screens (form -> audit -> results) and catches Python errors; it cannot judge visual layout."""
import os, runpy, sys, types
os.environ["AUDIT_ALLOW_PRIVATE_HOSTS"] = "1"; os.environ["AUDIT_CRAWL_DELAY"] = "0"
from tests.fake_site import start_server


class Rerun(Exception):
    pass


class D:
    def __getattr__(self, name): return D()
    def __call__(self, *a, **k): return D()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(())


def build(inputs):
    st = types.ModuleType("streamlit")
    st.session_state = STATE
    log = {"markdown": 0, "dataframes": 0, "errors": []}
    d = D()
    for n in ("set_page_config", "write", "caption", "info", "warning", "progress", "empty", "expander", "form",
              "status", "download_button"):
        setattr(st, n, d)
    st.markdown = lambda *a, **k: log.__setitem__("markdown", log["markdown"] + 1)
    st.dataframe = lambda df, **k: log.__setitem__("dataframes", log["dataframes"] + 1)
    st.error = lambda m, *a, **k: log["errors"].append(m)
    st.columns = lambda spec: [D() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda labels: [D() for _ in labels]
    st.text_input = lambda label, **k: inputs["url"] if "URL" in label else inputs["client"]
    st.selectbox = lambda label, options, index=0, **k: inputs["pages"]
    st.form_submit_button = lambda *a, **k: inputs["go"]
    st.button = lambda *a, **k: False
    def rerun(): raise Rerun()
    st.rerun = rerun
    sys.modules["streamlit"] = st
    return log


def run_app(inputs):
    log = build(inputs)
    try:
        runpy.run_path("app.py", run_name="__main__")
    except Rerun:
        pass
    return log


STATE = {}
srv = start_server()
url = f"http://127.0.0.1:{srv.server_port}/"

# 1. bad URL shows a friendly error and no crash
log = run_app({"url": "not a url", "client": "", "pages": 5, "go": True})
assert log["errors"] and "result" not in STATE, log

# 2. valid audit -> stored -> results screen renders
run_app({"url": url, "client": "Kiwi Widgets", "pages": 10, "go": True})
assert "result" in STATE and STATE["pdf"][:4] == b"%PDF"
log = run_app({"url": "", "client": "", "pages": 10, "go": False})
assert log["dataframes"] >= 8 and log["markdown"] > 20, log

# 3. unreachable site -> results screen shows an error, no crash
STATE.clear()
run_app({"url": "http://127.0.0.1:1/", "client": "", "pages": 5, "go": True})
assert STATE["result"].reachable is False
log = run_app({"url": "", "client": "", "pages": 5, "go": False})
assert log["errors"], log
print("APP STUB SMOKE TEST PASSED")

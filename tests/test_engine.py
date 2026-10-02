"""Offline end-to-end test: audits the fake site and checks the findings. Run: python -m tests.test_engine"""
import os
os.environ["AUDIT_ALLOW_PRIVATE_HOSTS"] = "1"
os.environ["AUDIT_CRAWL_DELAY"] = "0"

from auditor import run_audit
from tests.fake_site import start_server
from utils.helpers import validate_url


def main():
    srv = start_server()
    url = f"http://127.0.0.1:{srv.server_port}/"
    res = run_audit(url, "Kiwi Widgets", 20)
    ids = {i.id for i in res.issues}
    print("pages:", [(p.url.rsplit('/', 1)[-1] or '/', p.status, p.word_count) for p in res.pages])
    print("scores:", res.scores, res.ai_label)
    for i in res.issues:
        print(f"  {i.severity:8} {i.id:22} count={i.count}")
    print("broken:", [(b[1].rsplit('/', 1)[-1], b[2]) for b in res.broken_links])
    print("notes:", res.site.notes)
    expected = {"broken_links", "noindex", "title_missing", "h1_missing", "title_duplicate",
                "very_thin", "schema_partial", "schema_errors", "redirect_loops", "server_errors"}
    missing = expected - ids
    assert not missing, f"expected issues not raised: {missing}"
    assert res.site.robots_exists and res.site.sitemap_exists and res.site.sitemap_referenced_in_robots
    assert "robots_blocked" in ids, "sitemap /admin/panel should be skipped by robots.txt"
    assert any(p.discovered_via == "sitemap" for p in res.pages), "sitemap seeding failed"
    assert all(0 <= v <= 100 for v in res.scores.values())

    # failure paths must not crash
    bad = run_audit(f"http://127.0.0.1:{srv.server_port}/missing", "", 5)
    assert not bad.reachable and bad.issues[0].severity == "CRITICAL", bad.issues
    dead = run_audit("http://127.0.0.1:1/", "", 5)
    assert not dead.reachable and "connect" in dead.fatal_message.lower(), dead.fatal_message
    for raw in ["", "not a url", "ftp://x.com", "   "]:
        assert validate_url(raw)[0] is None, raw
    assert validate_url("example.com")[0] == "https://example.com/"
    print("ALL ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()

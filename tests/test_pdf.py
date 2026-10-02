import os
os.environ["AUDIT_ALLOW_PRIVATE_HOSTS"] = "1"; os.environ["AUDIT_CRAWL_DELAY"] = "0"
from auditor import run_audit
from reports.pdf_report import build_pdf
from tests.fake_site import start_server

srv = start_server()
res = run_audit(f"http://127.0.0.1:{srv.server_port}/", "Kiwi Widgets", 20)
os.makedirs("output", exist_ok=True)
data = build_pdf(res, "output/example_report.pdf")
assert data[:4] == b"%PDF"
print("PDF bytes:", len(data))

"""A tiny local website with deliberate SEO problems, used to test the audit engine offline."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOREM = ("Our team provides practical services for local businesses, explaining each step clearly and "
         "documenting results so customers always know what to expect from the work. ") * 6

ORG = {"@context": "https://schema.org", "@graph": [
    {"@type": "Organization", "name": "Kiwi Widgets", "url": "http://x/", "telephone": "+64 9 123 4567",
     "address": {"@type": "PostalAddress", "addressLocality": "Auckland"}},
    {"@type": "WebSite", "name": "Kiwi Widgets"}]}


def page(title, h1, body, desc="", extra_head="", links=""):
    d = f'<meta name="description" content="{desc}">' if desc else ""
    h = f"<h1>{h1}</h1>" if h1 else ""
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>{d}{extra_head}</head><body>'
            f'<nav><a href="/">Home</a> <a href="/about">About</a> <a href="/contact">Contact</a> {links}</nav>'
            f'{h}{body}<img src="/a.png" alt="logo"><img src="/b.png"><footer>footer</footer></body></html>')


PAGES = {
    "/": (200, "text/html", page(
        "Kiwi Widgets | Widget makers in Auckland", "Kiwi Widgets",
        f"<h2>What we do</h2><p>{LOREM}</p><h2>Why us</h2><p>{LOREM}</p>"
        '<a href="/services">Services</a> <a href="/blog/first-post">Blog</a> <a href="/missing">Old page</a>'
        '<a href="/redirect-loop">Loop</a> <a href="/thin">Thin</a> <a href="/notitle">No title</a> <a href="/broken-server">Server</a> <a href="/private">Private</a>'
        '<a href="https://example.org/ref">Ref</a>',
        desc="Kiwi Widgets designs and builds custom widgets for Auckland businesses, with clear pricing.",
        extra_head=f'<link rel="canonical" href="http://127.0.0.1:PORT/">'
                   f'<script type="application/ld+json">{json.dumps(ORG)}</script>')),
    "/about": (200, "text/html", page(
        "About", "About us", f"<h2>Our story</h2><p>{LOREM}</p>", desc="About Kiwi Widgets and the team.")),
    "/contact": (200, "text/html", page(
        "Contact Kiwi Widgets in Auckland", "Contact", '<p>Email hello@kiwiwidgets.example or call +64 9 123 4567</p>',
        desc="Contact Kiwi Widgets in Auckland by phone or email to discuss your next widget project today.")),
    "/services": (200, "text/html", page(
        "Services", "", f"<p>{LOREM}</p>", desc="Short.",
        extra_head='<script type="application/ld+json">{ not valid json </script>')),
    "/blog/first-post": (200, "text/html", page(
        "Blog: how widgets are made at Kiwi Widgets", "How widgets are made",
        f'<h2>Step one?</h2><p>{LOREM}</p><h2>Step two?</h2><p>{LOREM}</p>',
        desc="A behind-the-scenes look at how Kiwi Widgets makes widgets, from design to delivery.",
        extra_head='<meta property="og:type" content="article">')),
    "/thin": (200, "text/html", page("Services", "Thin", "<p>Just a few words here.</p>")),
    "/private": (200, "text/html", page(
        "Private area for staff members only", "Private", f"<p>{LOREM}</p>",
        desc="Private area. " * 8, extra_head='<meta name="robots" content="noindex, nofollow">')),
    "/notitle": (200, "text/html", "<html><body><h1>No title here</h1><p>%s</p></body></html>" % LOREM),
    "/orphan": (200, "text/html", page(
        "Orphan page that nothing links to at all", "Orphan", f"<p>{LOREM}</p>",
        desc="This page is only listed in the sitemap and has no inbound internal links at all.")),
    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /admin\nSitemap: http://127.0.0.1:PORT/sitemap.xml\n"),
    "/sitemap.xml": (200, "application/xml",
                     '<?xml version="1.0"?><urlset><url><loc>http://127.0.0.1:PORT/</loc></url>'
                     '<url><loc>http://127.0.0.1:PORT/orphan</loc></url>'
                     '<url><loc>http://127.0.0.1:PORT/admin/panel</loc></url></urlset>'),
    "/broken-server": (500, "text/html", "<h1>Oops</h1>"),
    "/a.png": (200, "image/png", "x"), "/b.png": (200, "image/png", "x"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep test output quiet
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/redirect-loop":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.end_headers()
            return
        status, ctype, body = PAGES.get(path, (404, "text/html", "<h1>Not found</h1>"))
        body = body.replace("PORT", str(self.server.server_port)).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_HEAD = do_GET


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

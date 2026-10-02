"""HTTP layer: one polite Session with timeouts, delay between requests, body-size cap and a small cache."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

import config
from utils.helpers import FRIENDLY_ERRORS, host_key, is_public_host
from urllib.parse import urlparse


@dataclass
class FetchResult:
    url: str
    status: int = 0
    final_url: str = ""
    history: list[str] = field(default_factory=list)   # intermediate redirect URLs
    headers: dict = field(default_factory=dict)
    text: str = ""
    content_type: str = ""
    elapsed: float = 0.0
    error_kind: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_kind and 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type or "xhtml" in self.content_type


class Fetcher:
    """Wraps requests.Session. Never raises: failures are returned as FetchResult.error_*."""

    def __init__(self, delay: float | None = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en",
        })
        self.session.max_redirects = config.MAX_REDIRECTS
        self.delay = config.CRAWL_DELAY_SECONDS if delay is None else delay
        self._last = 0.0
        self._cache: dict[str, FetchResult] = {}
        self.request_count = 0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str, read_body: bool = True, cache: bool = True) -> FetchResult:
        key = f"GET|{read_body}|{url}"
        if cache and key in self._cache:
            return self._cache[key]
        result = self._request("GET", url, read_body)
        if cache:
            self._cache[key] = result
        return result

    def head(self, url: str) -> FetchResult:
        """Light status check; falls back to GET when a server rejects HEAD."""
        key = f"HEAD|{url}"
        if key in self._cache:
            return self._cache[key]
        result = self._request("HEAD", url, False)
        if result.status in (403, 405, 501) and not result.error_kind:
            result = self._request("GET", url, False)
        self._cache[key] = result
        return result

    def _request(self, method: str, url: str, read_body: bool) -> FetchResult:
        res = FetchResult(url=url, final_url=url)
        if not is_public_host(urlparse(url).hostname or ""):
            res.error_kind, res.error = "blocked_host", FRIENDLY_ERRORS["blocked_host"]
            return res
        self._wait()
        self.request_count += 1
        start = time.monotonic()
        try:
            r = self.session.request(
                method, url, timeout=(config.CONNECT_TIMEOUT, config.READ_TIMEOUT),
                allow_redirects=True, stream=True,
            )
        except requests.exceptions.TooManyRedirects:
            res.error_kind, res.error = "redirect_loop", FRIENDLY_ERRORS["redirect_loop"]
        except requests.exceptions.SSLError:
            res.error_kind, res.error = "ssl", FRIENDLY_ERRORS["ssl"]
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
            res.error_kind, res.error = "timeout", FRIENDLY_ERRORS["timeout"]
        except requests.exceptions.ConnectionError:
            res.error_kind, res.error = "connection", FRIENDLY_ERRORS["connection"]
        except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema):
            res.error_kind, res.error = "invalid_url", FRIENDLY_ERRORS["invalid_url"]
        except requests.exceptions.RequestException as exc:
            res.error_kind, res.error = "other", f"{FRIENDLY_ERRORS['other']} ({type(exc).__name__})"
        else:
            try:
                res.status = r.status_code
                res.final_url = r.url
                res.history = [h.url for h in r.history]
                res.headers = {k.lower(): v for k, v in r.headers.items()}
                res.content_type = res.headers.get("content-type", "").lower()
                if not is_public_host(urlparse(r.url).hostname or ""):
                    res.error_kind, res.error = "blocked_host", FRIENDLY_ERRORS["blocked_host"]
                elif read_body and method == "GET" and (res.is_html or "xml" in res.content_type
                                                        or "text/plain" in res.content_type):
                    raw = b""
                    for chunk in r.iter_content(16384):
                        raw += chunk
                        if len(raw) >= config.MAX_RESPONSE_BYTES:
                            break
                    encoding = r.encoding or "utf-8"
                    try:
                        res.text = raw.decode(encoding, errors="replace")
                    except LookupError:
                        res.text = raw.decode("utf-8", errors="replace")
            except requests.exceptions.RequestException as exc:
                res.error_kind = "timeout" if "timed out" in str(exc).lower() else "other"
                res.error = FRIENDLY_ERRORS[res.error_kind]
            finally:
                r.close()
        res.elapsed = round(time.monotonic() - start, 2)
        return res


def same_origin_root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

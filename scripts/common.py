"""Shared helpers for the Wellows site audit scripts.

Every script writes its raw evidence under out/<domain>/data/ so that each
finding in the report can be traced back to a saved file.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

KIT_DIR = Path(__file__).resolve().parent.parent
# Where evidence and reports land. Override with AUDIT_OUT_DIR to point at a
# mounted disk when the kit runs as a service. Unset, it is the repo's out/.
OUT_ROOT = Path(os.environ.get("AUDIT_OUT_DIR") or (KIT_DIR / "out"))
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 25
MAX_RPS = 2.0  # polite ceiling for every script

CHALLENGE_MARKERS = [
    "just a moment", "cf-chl", "challenge-platform", "attention required",
    "cf-browser-verification", "captcha", "px-captcha", "_incapsula_",
    "datadome", "access denied", "request unsuccessful", "are you a robot",
    "verify you are human", "ddos protection",
]


def normalize_domain(raw: str) -> str:
    raw = raw.strip()
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).hostname or ""
    return host.lower().strip(".")


def out_dir(domain: str) -> Path:
    d = OUT_ROOT / domain / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(domain: str, name: str, obj) -> Path:
    p = out_dir(domain) / name
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return p


def load_json(domain: str, name: str, default=None):
    p = out_dir(domain) / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


class Fetcher:
    """requests.Session with a global rate limit and a uniform result record."""

    def __init__(self, ua: str = CHROME_UA, rps: float = MAX_RPS):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.min_gap = 1.0 / rps
        self._last = 0.0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last = time.monotonic()

    def get(self, url, ua=None, allow_redirects=True, headers=None, max_bytes=15_000_000, method="GET"):
        self._wait()
        h = dict(headers or {})
        if ua:
            h["User-Agent"] = ua
        rec = {"url": url, "ua": ua or self.s.headers["User-Agent"], "method": method}
        t0 = time.monotonic()
        try:
            r = self.s.request(method, url, allow_redirects=allow_redirects, headers=h,
                               timeout=DEFAULT_TIMEOUT, stream=True)
            body = b""
            if method != "HEAD":
                for chunk in r.iter_content(65536):
                    body += chunk
                    if len(body) > max_bytes:
                        rec["truncated"] = True
                        break
            rec.update({
                "status": r.status_code,
                "final_url": r.url,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "ttfb_ms": int(r.elapsed.total_seconds() * 1000),
                "headers": {k.lower(): v for k, v in r.headers.items()},
                "history": [{"status": h.status_code, "url": h.url,
                             "location": h.headers.get("Location")} for h in r.history],
                "bytes": len(body),
            })
            rec["_body"] = body
        except requests.RequestException as e:
            rec.update({"status": None, "error": f"{type(e).__name__}: {e}",
                        "elapsed_ms": int((time.monotonic() - t0) * 1000)})
            rec["_body"] = b""
        return rec


def text_of(rec) -> str:
    body = rec.get("_body", b"")
    enc = "utf-8"
    ct = rec.get("headers", {}).get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ct)
    if m:
        enc = m.group(1)
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def detect_challenge(rec) -> str | None:
    """Return a short reason if the response looks like a bot challenge or block."""
    st = rec.get("status")
    hdr = rec.get("headers", {})
    if hdr.get("cf-mitigated"):
        return f"cf-mitigated: {hdr['cf-mitigated']}"
    if st in (401, 402, 403, 429, 503):
        return f"HTTP {st}"
    if st is None:
        return rec.get("error", "no response")
    head = text_of(rec)[:6000].lower()
    if rec.get("bytes", 0) < 20000:
        for m in CHALLENGE_MARKERS:
            if m in head:
                return f"challenge marker '{m}' in body"
    return None


def strip_body(rec):
    r = dict(rec)
    r.pop("_body", None)
    return r


def base_url(domain: str) -> str:
    return f"https://{domain}"


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")

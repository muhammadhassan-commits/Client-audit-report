"""Step 4: server, edge and security checks.

TLS certificate and protocol versions, HTTP/2 and HTTP/3, compression,
conditional requests (ETag / Last-Modified / 304), caching on HTML and static
assets, security headers, URL normalisation redirects, and a one-GET-each
check of commonly exposed paths. No exploitation, no brute force.

Usage: python3 scripts/04_server_checks.py example.com
Writes: out/<domain>/data/server.json
Requires: 01_preflight.py has run.
"""
import datetime as dt
import shutil
import socket
import ssl
import subprocess
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from common import Fetcher, load_json, log, normalize_domain, save_json, text_of

SEC_HEADERS = ["strict-transport-security", "content-security-policy", "x-content-type-options",
               "x-frame-options", "referrer-policy", "permissions-policy", "cross-origin-opener-policy"]

EXPOSED = {
    "/.git/HEAD": lambda b: b.lstrip().startswith("ref:"),
    "/.env": lambda b: "=" in b and any(k in b.upper() for k in ("DB_", "APP_KEY", "SECRET", "PASSWORD", "API_KEY")),
    "/wp-json/wp/v2/users": lambda b: b.strip().startswith("[") and '"slug"' in b,
    "/xmlrpc.php": lambda b: "XML-RPC server accepts POST requests only" in b,
    "/readme.html": lambda b: "wordpress" in b.lower(),
    "/server-status": lambda b: "Apache Server Status" in b,
    "/phpinfo.php": lambda b: "phpinfo()" in b or "PHP Version" in b,
    "/wp-admin/": None,  # login exposure is normal for WordPress; record status only
    "/.DS_Store": lambda b: "Bud1" in b,
}


def tls_info(host):
    out = {}
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert = s.getpeercert()
                out["negotiated"] = s.version()
                exp = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                out["not_after"] = exp.isoformat()
                out["days_left"] = (exp - dt.datetime.utcnow()).days
                out["issuer"] = dict(x[0] for x in cert.get("issuer", []))
                out["san_count"] = len(cert.get("subjectAltName", []))
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    support = {}
    for name, ver in [("TLSv1.0", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1),
                      ("TLSv1.2", ssl.TLSVersion.TLSv1_2), ("TLSv1.3", ssl.TLSVersion.TLSv1_3)]:
        c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        try:
            c.minimum_version = ver
            c.maximum_version = ver
            if ver in (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1):
                c.set_ciphers("ALL:@SECLEVEL=0")
            with socket.create_connection((host, 443), timeout=10) as sock:
                with c.wrap_socket(sock, server_hostname=host):
                    support[name] = True
        except Exception:  # noqa: BLE001
            support[name] = False
    out["protocol_support"] = support
    out["note"] = "TLS 1.0/1.1 'False' can also mean the local OpenSSL refuses them; confirm with SSL Labs if it matters."
    return out


def curl_http_version(url, flag):
    if not shutil.which("curl"):
        return "curl not installed"
    try:
        r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-m", "20", flag, "-w", "%{http_version} %{http_code}", url],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def main(domain):
    pre = load_json(domain, "preflight.json")
    if not pre:
        sys.exit("run 01_preflight.py first")
    origin = pre["canonical_origin"]
    host = urlparse(origin).netloc
    home = pre["key_urls"]["home"]
    f = Fetcher()
    res = {"origin": origin}

    res["tls"] = tls_info(host)
    res["http_versions"] = {"http1.1": curl_http_version(home, "--http1.1"),
                            "http2": curl_http_version(home, "--http2"),
                            "http3": curl_http_version(home, "--http3-only")}
    r = f.get(home)
    h = r.get("headers", {})
    res["home_headers"] = h
    res["alt_svc"] = h.get("alt-svc")
    res["security_headers"] = {k: h.get(k) for k in SEC_HEADERS}
    res["missing_security_headers"] = [k for k in SEC_HEADERS if not h.get(k)]

    enc = {}
    for ae in ["br", "gzip", "identity"]:
        rr = f.get(home, headers={"Accept-Encoding": ae})
        enc[ae] = {"content_encoding": rr.get("headers", {}).get("content-encoding"), "bytes_on_wire_note": "requests decodes bodies; header shows server support"}
    res["compression"] = enc

    etag, lm = h.get("etag"), h.get("last-modified")
    cond = {"etag": etag, "last_modified": lm, "cache_control": h.get("cache-control")}
    if etag:
        rr = f.get(home, headers={"If-None-Match": etag})
        cond["if_none_match_status"] = rr.get("status")
    if lm:
        rr = f.get(home, headers={"If-Modified-Since": lm})
        cond["if_modified_since_status"] = rr.get("status")
    res["conditional_home"] = cond

    soup = BeautifulSoup(text_of(r), "lxml")
    assets = []
    for t in soup.find_all("link", rel=lambda v: v and "stylesheet" in v, href=True)[:2]:
        assets.append(urljoin(home, t["href"]))
    for t in soup.find_all("script", src=True)[:2]:
        assets.append(urljoin(home, t["src"]))
    for t in soup.find_all("img", src=True)[:2]:
        assets.append(urljoin(home, t["src"]))
    res["static_assets"] = []
    for a in assets:
        rr = f.get(a, method="HEAD")
        ah = rr.get("headers", {})
        res["static_assets"].append({"url": a, "status": rr.get("status"), "cache_control": ah.get("cache-control"),
                                     "content_encoding": ah.get("content-encoding"), "content_type": ah.get("content-type"),
                                     "cdn_cache": ah.get("cf-cache-status") or ah.get("x-cache"), "etag": bool(ah.get("etag"))})

    # URL normalisation on a deep page
    deep = next((u for k, u in pre["key_urls"].items() if k != "home"), home)
    p = urlparse(deep)
    variants = {}
    path = p.path or "/"
    toggled = path[:-1] if path.endswith("/") and len(path) > 1 else path + "/"
    for label, u in [("trailing_slash_toggled", f"{p.scheme}://{p.netloc}{toggled}"),
                     ("uppercase", f"{p.scheme}://{p.netloc}{path.upper()}"),
                     ("http", f"http://{p.netloc}{path}"),
                     ("index_html", f"{p.scheme}://{p.netloc}{path.rstrip('/')}/index.html")]:
        rr = f.get(u)
        variants[label] = {"url": u, "status": rr.get("status"), "final_url": rr.get("final_url"),
                           "hops": [x["status"] for x in rr.get("history", [])]}
    res["url_normalisation"] = {"base": deep, "variants": variants}

    exposed = {}
    for path, sig in EXPOSED.items():
        rr = f.get(origin + path, allow_redirects=False, max_bytes=200_000)
        body = text_of(rr)
        exposed[path] = {"status": rr.get("status"), "location": rr.get("headers", {}).get("location"),
                         "exposed": bool(rr.get("status") == 200 and sig and sig(body)),
                         "bytes": rr.get("bytes")}
    res["exposed_paths"] = exposed
    res["exposed_true"] = [k for k, v in exposed.items() if v["exposed"]]

    # burst check: 10 requests at the polite rate, look for 429/503
    burst = [f.get(home).get("status") for _ in range(10)]
    res["burst_10_at_2rps"] = burst

    out = save_json(domain, "server.json", res)
    log(f"OK server -> {out}")
    log(f"tls={res['tls'].get('negotiated')} days_left={res['tls'].get('days_left')} http={res['http_versions']}")
    log(f"missing_security_headers={res['missing_security_headers']} exposed={res['exposed_true']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 04_server_checks.py <domain>")
    main(normalize_domain(sys.argv[1]))

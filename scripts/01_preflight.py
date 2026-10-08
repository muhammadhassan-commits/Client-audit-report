"""Step 1: reachability, stack detection, host/protocol redirects, robots.txt,
llms.txt, security.txt, soft 404 and the key-URL set used by later steps.

Usage: python3 scripts/01_preflight.py example.com
Writes: out/<domain>/data/preflight.json, robots.txt, llms.txt (if any)
"""
import random
import re
import string
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from common import (Fetcher, base_url, detect_challenge, log, normalize_domain,
                    out_dir, save_json, strip_body, text_of)
from robots import Robots

STACK_SIGNS = [
    ("Cloudflare", lambda h, b: "cloudflare" in h.get("server", "") or "cf-ray" in h),
    ("Akamai", lambda h, b: "akamai" in h.get("server", "").lower() or "x-akamai-transformed" in h),
    ("Fastly", lambda h, b: "fastly" in (h.get("x-served-by", "") + h.get("via", "")).lower()),
    ("Amazon CloudFront", lambda h, b: "cloudfront" in (h.get("via", "") + h.get("x-cache", "")).lower()),
    ("Vercel", lambda h, b: "vercel" in h.get("server", "").lower() or "x-vercel-id" in h),
    ("Netlify", lambda h, b: "netlify" in h.get("server", "").lower()),
    ("Sucuri", lambda h, b: "sucuri" in h.get("server", "").lower() or "x-sucuri-id" in h),
    ("WordPress", lambda h, b: "wp-content" in b or "wp-json" in b or "wordpress" in h.get("x-powered-by", "").lower()),
    ("Webflow", lambda h, b: "webflow" in b[:20000].lower()),
    ("Shopify", lambda h, b: "cdn.shopify.com" in b),
    ("HubSpot CMS", lambda h, b: "hs-sites" in b or "hubspot" in h.get("x-powered-by", "").lower()),
    ("Next.js", lambda h, b: "__next" in b or "_next/static" in b),
    ("Nuxt", lambda h, b: "__nuxt" in b),
    ("Gatsby", lambda h, b: "___gatsby" in b),
    ("Framer", lambda h, b: "framerusercontent" in b),
    ("Wix", lambda h, b: "wixstatic" in b),
    ("Squarespace", lambda h, b: "squarespace" in b[:30000].lower()),
    ("Yoast SEO", lambda h, b: "yoast" in b.lower()),
    ("Rank Math", lambda h, b: "rank-math" in b.lower() or "rankmath" in b.lower()),
]


def main(domain):
    f = Fetcher()
    res = {"domain": domain}

    # Which host is canonical? Try apex and www over https.
    variants = {}
    for u in [f"https://{domain}/", f"http://{domain}/"]:
        alt = domain[4:] if domain.startswith("www.") else "www." + domain
        for uu in (u, u.replace(domain, alt)):
            r = f.get(uu)
            variants[uu] = {"status": r.get("status"), "final_url": r.get("final_url"),
                            "hops": [h["status"] for h in r.get("history", [])],
                            "chain": [h["url"] for h in r.get("history", [])] + [r.get("final_url")],
                            "error": r.get("error")}
    res["host_variants"] = variants
    home = f.get(base_url(domain) + "/")
    if home.get("status") is None:
        alt = domain[4:] if domain.startswith("www.") else "www." + domain
        home = f.get(f"https://{alt}/")
    if home.get("status") is None:
        res["reachable"] = False
        res["error"] = home.get("error")
        save_json(domain, "preflight.json", res)
        log(f"UNREACHABLE: {home.get('error')}")
        sys.exit(2)
    final = urlparse(home["final_url"])
    origin = f"{final.scheme}://{final.netloc}"
    res["reachable"] = True
    res["canonical_origin"] = origin
    res["home"] = strip_body(home)
    res["home_challenge"] = detect_challenge(home)
    html = text_of(home)
    (out_dir(domain) / "home.html").write_text(html, encoding="utf-8")
    hdr = home.get("headers", {})
    res["stack"] = [name for name, fn in STACK_SIGNS if fn(hdr, html)]
    res["server_headers"] = {k: hdr.get(k) for k in ("server", "x-powered-by", "via", "cf-ray", "x-cache", "cf-cache-status", "age")}

    # robots.txt (all host/protocol variants)
    robots_variants = {}
    for u in [origin + "/robots.txt", origin.replace("https://", "http://") + "/robots.txt"]:
        r = f.get(u)
        robots_variants[u] = {"status": r.get("status"), "final_url": r.get("final_url"),
                              "hops": len(r.get("history", [])), "bytes": r.get("bytes"),
                              "content_type": r.get("headers", {}).get("content-type")}
    rb = f.get(origin + "/robots.txt")
    robots_txt = text_of(rb) if rb.get("status") == 200 else ""
    (out_dir(domain) / "robots.txt").write_text(robots_txt, encoding="utf-8")
    rp = Robots(robots_txt)
    res["robots"] = {
        "status": rb.get("status"), "bytes": rb.get("bytes"),
        "content_type": rb.get("headers", {}).get("content-type"),
        "challenge": detect_challenge(rb), "variants": robots_variants,
        "groups": {g: [("Allow: " if a else "Disallow: ") + p for a, p in rules] for g, rules in rp.groups.items()},
        "sitemaps": rp.sitemaps, "other_directives": rp.other, "parse_warnings": rp.parse_warnings,
        "cloudflare_managed_signature": ("cloudflare" in robots_txt.lower() and "managed" in robots_txt.lower())
            or "content-signal" in robots_txt.lower(),
    }

    # Sitemaps: declared plus common locations
    sm_candidates = list(dict.fromkeys(rp.sitemaps + [origin + "/sitemap.xml", origin + "/sitemap_index.xml", origin + "/wp-sitemap.xml"]))
    sm = {}
    for u in sm_candidates:
        r = f.get(u, max_bytes=2_000_000)
        sm[u] = {"status": r.get("status"), "final_url": r.get("final_url"),
                 "content_type": r.get("headers", {}).get("content-type"), "bytes": r.get("bytes")}
    res["sitemap_candidates"] = sm

    # llms.txt family, security.txt, humans, ads.txt (presence only)
    extras = {}
    for path in ["/llms.txt", "/llms-full.txt", "/.well-known/llms.txt", "/.well-known/security.txt",
                 "/favicon.ico", "/manifest.json", "/site.webmanifest", "/.well-known/ai-plugin.json"]:
        r = f.get(origin + path, max_bytes=30_000_000)
        e = {"status": r.get("status"), "final_url": r.get("final_url"), "bytes": r.get("bytes"),
             "content_type": r.get("headers", {}).get("content-type"),
             "last_modified": r.get("headers", {}).get("last-modified"), "truncated": r.get("truncated", False)}
        if r.get("status") == 200 and path.startswith("/llms"):
            t = text_of(r)
            (out_dir(domain) / path.strip("/").replace("/", "_")).write_text(t, encoding="utf-8")
            links = re.findall(r"\]\((https?://[^)\s]+)\)", t)
            e["link_count"] = len(links)
            e["first_lines"] = t.splitlines()[:8]
            # sample up to 25 links for status
            checks = []
            for l in links[:25]:
                lr = f.get(l, method="HEAD")
                if lr.get("status") in (405, 403, None):
                    lr = f.get(l, max_bytes=50_000)
                checks.append({"url": l, "status": lr.get("status")})
            e["link_sample"] = checks
            e["link_sample_non200"] = [c for c in checks if c["status"] != 200]
        extras[path] = e
    res["special_files"] = extras

    # Soft 404 test
    junk = "".join(random.choices(string.ascii_lowercase, k=14))
    r404 = f.get(f"{origin}/wellows-audit-{junk}-not-a-page/")
    res["soft404"] = {"url": r404["url"], "status": r404.get("status"), "final_url": r404.get("final_url"),
                      "bytes": r404.get("bytes"),
                      "title": (BeautifulSoup(text_of(r404), "lxml").title.string.strip()
                                if r404.get("status") and BeautifulSoup(text_of(r404), "lxml").title and BeautifulSoup(text_of(r404), "lxml").title.string else None)}

    # Key URLs from homepage nav: pricing, blog, features, docs/help, about, contact
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        u = urljoin(home["final_url"], a["href"]).split("#")[0]
        if urlparse(u).netloc == final.netloc:
            links.append((u, (a.get_text(" ", strip=True) or "").lower()))
    pats = {"pricing": r"pric|plans", "blog": r"/blog|/resources|/insights|/articles",
            "features": r"feature|product|solution|platform", "help": r"help|support|docs|knowledge|kb|faq",
            "about": r"about|company", "contact": r"contact"}
    key = {"home": home["final_url"]}
    for k, p in pats.items():
        for u, t in links:
            if re.search(p, u.lower()) and u.rstrip("/") != home["final_url"].rstrip("/"):
                key[k] = u
                break
    res["key_urls"] = key
    # Subdomains seen in links
    subs = sorted({urlparse(urljoin(home["final_url"], a["href"])).netloc for a in soup.find_all("a", href=True)
                   if urlparse(urljoin(home["final_url"], a["href"])).netloc.endswith(domain.removeprefix("www."))
                   and urlparse(urljoin(home["final_url"], a["href"])).netloc != final.netloc})
    res["linked_subdomains"] = subs

    p = save_json(domain, "preflight.json", res)
    log(f"OK preflight -> {p}")
    log(f"origin={origin} stack={res['stack']} challenge_on_home={res['home_challenge']}")
    log(f"key_urls={key}")
    log(f"subdomains={subs}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 01_preflight.py <domain>")
    main(normalize_domain(sys.argv[1]))

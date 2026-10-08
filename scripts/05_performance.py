"""Step 5: Core Web Vitals (field) and Lighthouse lab data via the PageSpeed
Insights API, mobile and desktop, for the key URLs.

Set PSI_API_KEY in the environment for a reliable quota (free key from
Google Cloud console). Without a key the API often rate-limits.

Usage: python3 scripts/05_performance.py example.com
Writes: out/<domain>/data/performance.json
"""
import os
import sys
import time

import requests

from common import load_json, log, normalize_domain, save_json

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
FIELD = {"LARGEST_CONTENTFUL_PAINT_MS": "LCP_ms", "INTERACTION_TO_NEXT_PAINT": "INP_ms",
         "CUMULATIVE_LAYOUT_SHIFT_SCORE": "CLS_x100", "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "TTFB_ms",
         "FIRST_CONTENTFUL_PAINT_MS": "FCP_ms"}
LAB = ["largest-contentful-paint", "total-blocking-time", "cumulative-layout-shift", "first-contentful-paint",
       "speed-index", "server-response-time", "render-blocking-resources", "unused-javascript", "unused-css-rules",
       "modern-image-formats", "uses-text-compression", "total-byte-weight", "third-party-summary", "uses-long-cache-ttl"]


def run(url, strategy, key):
    params = [("url", url), ("strategy", strategy)] + [("category", c) for c in ("performance", "accessibility", "seo", "best-practices")]
    if key:
        params.append(("key", key))
    for attempt in range(3):
        r = requests.get(API, params=params, timeout=120)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        break
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
    j = r.json()
    out = {"field_url": {}, "field_origin": {}}
    for scope, k in (("field_url", "loadingExperience"), ("field_origin", "originLoadingExperience")):
        le = j.get(k, {})
        out[scope]["overall"] = le.get("overall_category")
        for mk, name in FIELD.items():
            m = le.get("metrics", {}).get(mk)
            if m:
                out[scope][name] = {"p75": m.get("percentile"), "category": m.get("category")}
    lr = j.get("lighthouseResult", {})
    out["scores"] = {c: round((v.get("score") or 0) * 100) for c, v in lr.get("categories", {}).items()}
    audits = lr.get("audits", {})
    out["lab"] = {a: {"display": audits.get(a, {}).get("displayValue"), "score": audits.get(a, {}).get("score"),
                      "numeric": audits.get(a, {}).get("numericValue")} for a in LAB if a in audits}
    out["failed_seo_audits"] = [k for k, v in audits.items() if v.get("score") == 0 and k in
                                [r["id"] for r in lr.get("categories", {}).get("seo", {}).get("auditRefs", [])]]
    out["failed_a11y_audits"] = [k for k, v in audits.items() if v.get("score") == 0 and k in
                                 [r["id"] for r in lr.get("categories", {}).get("accessibility", {}).get("auditRefs", [])]]
    return out


def main(domain):
    pre = load_json(domain, "preflight.json")
    if not pre:
        sys.exit("run 01_preflight.py first")
    key = os.environ.get("PSI_API_KEY")
    urls = list(dict.fromkeys(pre["key_urls"].values()))[:5]
    res = {"api_key_used": bool(key), "results": {}}
    for u in urls:
        for strat in ("mobile", "desktop"):
            log(f"PSI {strat} {u}")
            try:
                res["results"].setdefault(u, {})[strat] = run(u, strat, key)
            except requests.RequestException as e:
                res["results"].setdefault(u, {})[strat] = {"error": str(e)}
    p = save_json(domain, "performance.json", res)
    log(f"OK performance -> {p}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 05_performance.py <domain>")
    main(normalize_domain(sys.argv[1]))

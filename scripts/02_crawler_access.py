"""Step 2: AI and search crawler access matrix.

For every agent in framework/agents.json and every key URL from preflight:
robots.txt verdict (RFC 9309 matching), HTTP status with the agent's real UA,
response size vs a Chrome baseline, challenge/block detection, X-Robots-Tag,
meta robots (generic and agent-specific) and AI opt-out signals.

Usage: python3 scripts/02_crawler_access.py example.com
Writes: out/<domain>/data/crawler_access.json
Requires: 01_preflight.py has run.
"""
import json
import re
import sys

from bs4 import BeautifulSoup

from common import (KIT_DIR, OUT_ROOT, Fetcher, detect_challenge, load_json,
                    log, normalize_domain, save_json, strip_body, text_of)
from robots import Robots

OPT_OUT = re.compile(r"\b(noai|noimageai|nosnippet|max-snippet\s*:\s*0|noindex|none)\b", re.I)


def meta_signals(html: str):
    soup = BeautifulSoup(html, "lxml")
    metas = {}
    for m in soup.find_all("meta"):
        n = (m.get("name") or "").lower()
        if n in ("robots", "googlebot", "bingbot", "gptbot", "googlebot-news", "google-extended") or n.endswith("bot"):
            metas[n] = m.get("content", "")
    nosnippet_blocks = len(soup.select("[data-nosnippet]"))
    return metas, nosnippet_blocks


def main(domain):
    pre = load_json(domain, "preflight.json")
    if not pre:
        sys.exit("run 01_preflight.py first")
    agents = json.loads((KIT_DIR / "framework" / "agents.json").read_text())["agents"]
    robots_txt = (OUT_ROOT / domain / "data" / "robots.txt").read_text(encoding="utf-8")
    rp = Robots(robots_txt)
    keys = pre["key_urls"]
    f = Fetcher()

    baseline = {}
    for k, u in keys.items():
        r = f.get(u)
        baseline[k] = {"url": u, "status": r.get("status"), "bytes": r.get("bytes"),
                       "challenge": detect_challenge(r)}
    rows = []
    for a in agents:
        row = {k: a[k] for k in ("name", "operator", "type", "powers", "robots_token", "verify")}
        row["robots"] = {}
        for k, u in keys.items():
            allowed, group, rule = rp.verdict(a["robots_token"], u)
            row["robots"][k] = {"allowed": allowed, "group": group, "rule": rule}
        row["robots_group"] = rp.group_for(a["robots_token"])
        row["fetch"] = {}
        if a["ua"]:
            for k, u in keys.items():
                r = f.get(u, ua=a["ua"])
                html = text_of(r) if r.get("status") == 200 else ""
                metas, nosnip = meta_signals(html) if html else ({}, 0)
                b = baseline[k]["bytes"] or 0
                xrt = r.get("headers", {}).get("x-robots-tag")
                row["fetch"][k] = {
                    "status": r.get("status"), "bytes": r.get("bytes"),
                    "size_vs_chrome": round(r.get("bytes", 0) / b, 3) if b else None,
                    "challenge": detect_challenge(r), "x_robots_tag": xrt,
                    "x_robots_optout": bool(xrt and OPT_OUT.search(xrt)),
                    "meta_robots": metas,
                    "meta_optout": {n: c for n, c in metas.items() if OPT_OUT.search(c or "")},
                    "data_nosnippet_blocks": nosnip,
                    "hops": [h["status"] for h in r.get("history", [])],
                    "final_url": r.get("final_url"), "error": r.get("error"),
                }
        # summary flags
        blocked_robots = [k for k, v in row["robots"].items() if not v["allowed"]]
        blocked_fetch = [k for k, v in row["fetch"].items() if v["challenge"] or (v["status"] or 0) >= 400]
        small = [k for k, v in row["fetch"].items() if v["size_vs_chrome"] is not None and v["size_vs_chrome"] < 0.8]
        row["summary"] = {"robots_blocked_on": blocked_robots, "fetch_blocked_on": blocked_fetch,
                          "much_smaller_than_chrome_on": small}
        rows.append(row)
        log(f"{a['name']:<22} robots_blocked={blocked_robots} fetch_blocked={blocked_fetch} small={small}")

    # Linked subdomains: robots + home for Chrome and Googlebot
    subs = {}
    gb = next(a for a in agents if a["name"] == "Googlebot")
    for host in pre.get("linked_subdomains", [])[:10]:
        rr = f.get(f"https://{host}/robots.txt")
        hc = f.get(f"https://{host}/")
        hg = f.get(f"https://{host}/", ua=gb["ua"])
        soup = BeautifulSoup(text_of(hc), "lxml") if hc.get("status") == 200 else None
        canon = soup.find("link", rel="canonical") if soup else None
        mr = soup.find("meta", attrs={"name": "robots"}) if soup else None
        subs[host] = {"robots_status": rr.get("status"), "robots_txt": text_of(rr)[:3000] if rr.get("status") == 200 else None,
                      "home_status_chrome": hc.get("status"), "home_status_googlebot": hg.get("status"),
                      "final_url": hc.get("final_url"), "x_robots_tag": hc.get("headers", {}).get("x-robots-tag"),
                      "meta_robots": mr.get("content") if mr else None,
                      "canonical": canon.get("href") if canon else None,
                      "challenge_googlebot": detect_challenge(hg)}
    out = {"key_urls": keys, "chrome_baseline": baseline, "agents": rows, "subdomains": subs,
           "robots_other_directives": rp.other,
           "method_note": "Requests sent from the auditor's network with each crawler's published user agent. "
                          "This proves robots.txt rules and how the server or CDN treats that user agent. "
                          "It does not prove how the CDN treats requests from the crawler's own IP ranges."}
    p = save_json(domain, "crawler_access.json", out)
    log(f"OK crawler access -> {p}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 02_crawler_access.py <domain>")
    main(normalize_domain(sys.argv[1]))

"""Step 6: raw HTML vs rendered DOM parity (what non-JS crawlers miss),
mobile vs desktop parity, console errors, cookie-banner coverage, and a
reader-mode style extraction check.

Needs Playwright:  pip install playwright && python3 -m playwright install chromium
If Playwright is missing the script records that and exits cleanly, and the
related checks become "Not tested" with that reason.

Usage: python3 scripts/06_render.py example.com
Writes: out/<domain>/data/render.json and screenshots in out/<domain>/data/shots/
"""
import re
import sys

from bs4 import BeautifulSoup

from common import Fetcher, load_json, log, normalize_domain, out_dir, save_json, text_of


def summarize(html):
    soup = BeautifulSoup(html, "lxml")
    canon = soup.find("link", rel=lambda v: v and "canonical" in v)
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    jl = soup.find_all("script", type="application/ld+json")
    for s in soup(["script", "style", "noscript", "template", "svg"]):
        s.extract()
    text = soup.get_text(" ", strip=True)
    return {"title": soup.title.get_text(strip=True) if soup.title else None,
            "canonical": canon.get("href") if canon else None,
            "meta_robots": mr.get("content") if mr else None,
            "h1": [h.get_text(" ", strip=True)[:120] for h in soup.find_all("h1")][:3],
            "h2_count": len(soup.find_all("h2")),
            "words": len(re.findall(r"\w+", text)),
            "links": len(soup.find_all("a", href=True)),
            "jsonld_blocks": len(jl),
            "tables": len(soup.find_all("table"))}


def main(domain):
    pre = load_json(domain, "preflight.json")
    if not pre:
        sys.exit("run 01_preflight.py first")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        save_json(domain, "render.json", {"skipped": "Playwright not installed (pip install playwright && python3 -m playwright install chromium)"})
        log("SKIPPED: Playwright not installed")
        return
    shots = out_dir(domain) / "shots"
    shots.mkdir(exist_ok=True)
    f = Fetcher()
    urls = list(dict.fromkeys(pre["key_urls"].values()))[:6]
    res = {"pages": {}}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for u in urls:
            raw = summarize(text_of(f.get(u)))
            entry = {"raw": raw}
            for label, kw in (("desktop", {"viewport": {"width": 1366, "height": 900}}),
                              ("mobile", {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "user_agent":
                                          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"})):
                ctx = b.new_context(**kw)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)[:200]))
                page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
                try:
                    page.goto(u, wait_until="networkidle", timeout=60000)
                except Exception as e:  # noqa: BLE001
                    entry[label] = {"error": str(e)[:200]}
                    ctx.close()
                    continue
                rendered = summarize(page.content())
                # largest fixed/sticky overlay coverage (cookie banners, interstitials)
                cover = page.evaluate("""() => {
                  const vw = innerWidth, vh = innerHeight; let best = 0, sel = null;
                  for (const el of document.querySelectorAll('body *')) {
                    const s = getComputedStyle(el);
                    if (!['fixed','sticky'].includes(s.position) || s.display==='none' || s.visibility==='hidden') continue;
                    const r = el.getBoundingClientRect();
                    const a = Math.max(0, Math.min(r.right,vw)-Math.max(r.left,0)) * Math.max(0, Math.min(r.bottom,vh)-Math.max(r.top,0));
                    if (a/(vw*vh) > best) { best = a/(vw*vh); sel = el.tagName.toLowerCase() + (el.id?('#'+el.id):'') + (el.className&&typeof el.className==='string'?('.'+el.className.split(' ')[0]):''); }
                  }
                  return {share: Math.round(best*100), selector: sel};
                }""")
                slug = re.sub(r"[^a-z0-9]+", "-", u.lower())[-60:]
                page.screenshot(path=str(shots / f"{label}-{slug}.png"))
                entry[label] = {"rendered": rendered, "console_errors": errors[:10], "largest_overlay": cover}
                ctx.close()
            d = entry.get("desktop", {}).get("rendered")
            if d:
                entry["parity"] = {
                    "title_same": raw["title"] == d["title"], "canonical_same": raw["canonical"] == d["canonical"],
                    "h1_same": raw["h1"] == d["h1"], "raw_words_share": round(raw["words"] / max(1, d["words"]), 2),
                    "raw_links_share": round(raw["links"] / max(1, d["links"]), 2),
                    "jsonld_raw_vs_rendered": [raw["jsonld_blocks"], d["jsonld_blocks"]]}
            m = entry.get("mobile", {}).get("rendered")
            if d and m:
                entry["mobile_parity"] = {"h1_same": d["h1"] == m["h1"], "words_ratio": round(m["words"] / max(1, d["words"]), 2),
                                          "links_ratio": round(m["links"] / max(1, d["links"]), 2), "jsonld_same": d["jsonld_blocks"] == m["jsonld_blocks"]}
            res["pages"][u] = entry
            log(f"rendered {u}: {entry.get('parity')}")
        b.close()
    p = save_json(domain, "render.json", res)
    log(f"OK render -> {p}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 06_render.py <domain>")
    main(normalize_domain(sys.argv[1]))

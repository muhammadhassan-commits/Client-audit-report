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

from urllib.parse import urlparse

from common import (OUT_ROOT, Fetcher, load_json, log, normalize_domain,
                    out_dir, save_json, text_of)


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


def raw_html(f, url, domain):
    """The server-rendered HTML for url, with one retry and a saved fallback.

    A raw fetch that comes back empty, which a TLS-intercepting proxy or a
    transient network error can cause, would otherwise be summarised as 0 words
    and 0 links and read as a total rendering-parity failure. M1 is a Critical
    check, so an empty fetch must never be mistaken for an empty page.
    """
    html = text_of(f.get(url))
    if html.strip():
        return html
    html = text_of(f.get(url))                      # one retry
    if html.strip():
        return html
    if urlparse(url).path in ("", "/"):             # preflight saved the homepage
        saved = OUT_ROOT / domain / "data" / "home.html"
        if saved.is_file():
            log(f"raw fetch of {url} came back empty twice, using the saved home.html")
            return saved.read_text(encoding="utf-8", errors="replace")
    log(f"WARNING raw fetch of {url} came back empty; parity for it is not reliable")
    return ""


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
            raw = summarize(raw_html(f, u, domain))
            entry = {"raw": raw}
            slug = re.sub(r"[^a-z0-9]+", "-", u.lower())[-60:]
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
            # The same page with JavaScript on and off, full height, so the
            # parity numbers above have a picture a client can read. A crawler
            # that does not run JavaScript sees the second one.
            for label, js in (("js-on", True), ("js-off", False)):
                ctx = b.new_context(viewport={"width": 1366, "height": 900},
                                    java_script_enabled=js)
                page = ctx.new_page()
                try:
                    page.goto(u, wait_until="networkidle" if js else "load", timeout=60000)
                    page.wait_for_timeout(2500)
                    page.screenshot(path=str(shots / f"{label}-{slug}.png"), full_page=True)
                    # Measure what is painted, not what is in the markup. Text
                    # that sits in the DOM behind opacity 0 or under a preloader
                    # still counts in page.content(), which is how a homepage
                    # that renders as a blank spinner once scored 80 percent.
                    entry.setdefault("painted", {})[label] = page.evaluate(r"""() => {
                      const seen = e => { const s = getComputedStyle(e);
                        return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05
                               && e.getBoundingClientRect().height > 0; };
                      const t = (document.body.innerText || '').replace(/[ \t\n\r]+/g, ' ').trim();
                      return {words: t ? t.split(' ').length : 0,
                              visible_links: [...document.querySelectorAll('a[href]')].filter(seen).length,
                              visible_h1: [...document.querySelectorAll('h1')].filter(seen).length,
                              h1_in_markup: document.querySelectorAll('h1').length,
                              blocking_overlay: !!document.querySelector(
                                '.preloader, #preloader, .loader, .page-loader, .spinner')};
                    }""")
                    if not js:
                        entry["js_off"] = summarize(page.content())
                except Exception as e:  # noqa: BLE001
                    entry.setdefault("js_capture_errors", {})[label] = str(e)[:200]
                finally:
                    ctx.close()
            pt = entry.get("painted", {})
            if pt.get("js-on") and pt.get("js-off"):
                on, off = pt["js-on"], pt["js-off"]
                entry["painted_parity"] = {
                    "words_share": round(off["words"] / max(1, on["words"]), 2),
                    "visible_links_share": round(off["visible_links"] / max(1, on["visible_links"]), 2),
                    "visible_h1_js_off": off["visible_h1"],
                    "h1_in_markup": off["h1_in_markup"],
                    "preloader_present": off["blocking_overlay"]}
            if entry.get("js_off") and entry.get("desktop", {}).get("rendered"):
                jd, dd = entry["js_off"], entry["desktop"]["rendered"]
                entry["js_parity"] = {
                    "title_same": jd["title"] == dd["title"],
                    "h1_same": jd["h1"] == dd["h1"],
                    "words_share": round(jd["words"] / max(1, dd["words"]), 2),
                    "links_share": round(jd["links"] / max(1, dd["links"]), 2),
                    "jsonld_js_off_vs_on": [jd["jsonld_blocks"], dd["jsonld_blocks"]]}

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

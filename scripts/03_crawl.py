"""Step 3: sitemap audit + sampled crawl with per-page on-page extraction.

Usage: python3 scripts/03_crawl.py example.com [--max-pages 150] [--link-check 300]
Writes: out/<domain>/data/sitemaps.json, crawl.jsonl, crawl_summary.json, links.json
Requires: 01_preflight.py has run.
"""
import argparse
import collections
import gzip
import json
import math
import random
import re
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from lxml import etree

from common import (Fetcher, detect_challenge, load_json, log, normalize_domain,
                    out_dir, save_json, text_of)

GENERIC_ANCHORS = {"click here", "here", "read more", "learn more", "more", "this", "link", "go"}
DEPRECATED = ["font", "center", "marquee", "blink", "big", "strike", "tt", "frameset", "frame"]


def parse_sitemaps(f, start, origin_host, limit=100_000):
    seen_maps, urls, maps = set(), collections.defaultdict(list), []
    queue = list(start)
    while queue and len(seen_maps) < 500:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        r = f.get(sm, max_bytes=60_000_000)
        rec = {"url": sm, "status": r.get("status"), "bytes": r.get("bytes"),
               "content_type": r.get("headers", {}).get("content-type"), "kind": None, "count": 0,
               "with_lastmod": 0, "errors": None}
        body = r.get("_body", b"")
        if r.get("status") != 200 or not body:
            maps.append(rec)
            continue
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError as e:
                rec["errors"] = f"gzip: {e}"
        try:
            root = etree.fromstring(body, parser=etree.XMLParser(recover=True, huge_tree=True))
        except etree.XMLSyntaxError as e:
            rec["errors"] = f"xml: {e}"
            maps.append(rec)
            continue
        if root is None:
            rec["errors"] = "empty or invalid XML"
            maps.append(rec)
            continue
        tag = etree.QName(root).localname
        rec["kind"] = tag
        for node in root:
            if not isinstance(node.tag, str):
                continue
            loc = lastmod = None
            for c in node:
                if not isinstance(c.tag, str):
                    continue
                ln = etree.QName(c).localname
                if ln == "loc":
                    loc = (c.text or "").strip()
                elif ln == "lastmod":
                    lastmod = (c.text or "").strip()
            if not loc:
                continue
            rec["count"] += 1
            if lastmod:
                rec["with_lastmod"] += 1
            if tag == "sitemapindex":
                queue.append(loc)
            elif len(urls) < limit:
                urls[loc].append({"sitemap": sm, "lastmod": lastmod})
        maps.append(rec)
    off_host = [u for u in urls if urlparse(u).netloc != origin_host]
    multi = [u for u, v in urls.items() if len({x["sitemap"] for x in v}) > 1]
    return maps, urls, off_host, multi


def words(text):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)


def extract(rec, origin_host):
    html = text_of(rec)
    soup = BeautifulSoup(html, "lxml")
    out = {}
    h = rec.get("headers", {})
    out["x_robots_tag"] = h.get("x-robots-tag")
    out["content_type"] = h.get("content-type")
    out["html_bytes"] = rec.get("bytes")
    html_tag = soup.find("html")
    out["lang"] = html_tag.get("lang") if html_tag else None
    head = soup.head
    first_meta = head.find("meta") if head else None
    out["charset_first"] = bool(first_meta and (first_meta.get("charset") or "charset" in (first_meta.get("content") or "").lower()))
    out["viewport_count"] = len(soup.find_all("meta", attrs={"name": "viewport"}))
    titles = soup.find_all("title")
    t = titles[0].get_text(strip=True) if titles else ""
    out.update(title=t, title_len=len(t), title_count=len(titles))
    descs = soup.find_all("meta", attrs={"name": re.compile("^description$", re.I)})
    d = (descs[0].get("content") or "").strip() if descs else ""
    out.update(description=d, description_len=len(d), description_count=len(descs))
    body = soup.body
    out["meta_in_body"] = len(body.find_all("meta", attrs={"name": True})) if body else 0
    canons = soup.find_all("link", rel=lambda v: v and "canonical" in v)
    out["canonical_count"] = len(canons)
    out["canonical"] = urljoin(rec["final_url"], canons[0].get("href")) if canons else None
    link_hdr = h.get("link", "")
    m = re.search(r'<([^>]+)>\s*;\s*rel="?canonical"?', link_hdr)
    out["canonical_header"] = m.group(1) if m else None
    mr = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    out["meta_robots"] = mr.get("content") if mr else None
    # headings
    hs = soup.find_all(re.compile("^h[1-6]$"))
    levels = [int(x.name[1]) for x in hs]
    out["h1_count"] = levels.count(1)
    out["h1"] = [x.get_text(" ", strip=True)[:150] for x in soup.find_all("h1")][:3]
    out["heading_skips"] = sum(1 for a, b in zip(levels, levels[1:]) if b > a + 1)
    out["empty_headings"] = sum(1 for x in hs if len(x.get_text(strip=True)) < 3)
    out["headings_total"] = len(hs)
    h23 = [x for x in hs if x.name in ("h2", "h3")]
    out["h23_with_id"] = sum(1 for x in h23 if x.get("id") or x.find(attrs={"id": True}))
    out["h23_total"] = len(h23)
    out["question_headings"] = sum(1 for x in h23 if x.get_text(strip=True).endswith("?"))
    # answer-first: words in first <p> after each h2
    firsts = []
    for x in soup.find_all("h2"):
        p = x.find_next("p")
        if p:
            firsts.append(len(words(p.get_text(" ", strip=True))))
    out["h2_first_para_words_median"] = sorted(firsts)[len(firsts) // 2] if firsts else None
    # text
    for s in soup(["script", "style", "noscript", "template", "svg"]):
        s.extract()
    vis = soup.get_text(" ", strip=True)
    out["word_count"] = len(words(vis))
    out["text_html_ratio"] = round(len(vis) / max(1, len(html)), 3)
    main = soup.find("main") or soup.find(attrs={"role": "main"})
    out["landmarks"] = {k: bool(soup.find(k)) for k in ("main", "article", "nav", "header", "footer")}
    out["main_word_share"] = round(len(words(main.get_text(" ", strip=True))) / max(1, out["word_count"]), 2) if main else None
    out["tables"] = len(soup.find_all("table"))
    out["lists"] = len(soup.find_all(["ol", "ul"]))
    out["lorem_or_todo"] = bool(re.search(r"lorem ipsum|\bTODO\b|dummy text", vis, re.I))
    # links
    internal, external, http_links, nofollow_int, generic = [], [], 0, 0, 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urljoin(rec["final_url"], href).split("#")[0]
        host = urlparse(u).netloc
        if u.startswith("http://"):
            http_links += 1
        txt = a.get_text(" ", strip=True).lower()
        if txt in GENERIC_ANCHORS:
            generic += 1
        if host == origin_host:
            internal.append(u)
            if "nofollow" in (a.get("rel") or []):
                nofollow_int += 1
        elif host:
            external.append(u)
    out.update(internal_links=len(internal), external_links=len(external), http_links=http_links,
               internal_nofollow=nofollow_int, generic_anchors=generic)
    out["_internal"] = list(dict.fromkeys(internal))
    out["_external"] = list(dict.fromkeys(external))
    # images
    imgs = soup.find_all("img")
    out["images"] = len(imgs)
    out["img_missing_alt"] = sum(1 for i in imgs if i.get("alt") is None)
    out["img_no_dims"] = sum(1 for i in imgs if not (i.get("width") and i.get("height")))
    out["img_lazy"] = sum(1 for i in imgs if i.get("loading") == "lazy")
    srcs = [(i.get("src") or i.get("data-src") or "") for i in imgs]
    out["img_legacy_format"] = sum(1 for s in srcs if re.search(r"\.(jpe?g|png|gif|bmp)(\?|$)", s, re.I))
    out["img_srcset"] = sum(1 for i in imgs if i.get("srcset"))
    out["mixed_content"] = sum(1 for tag in soup.find_all(["img", "script", "iframe", "source", "video", "audio"])
                               if (tag.get("src") or "").startswith("http://")) + \
        sum(1 for l in soup.find_all("link", href=True) if l["href"].startswith("http://") and "stylesheet" in (l.get("rel") or []))
    # structured data
    types, errors, dates, authors, ids, sameas = [], 0, {}, [], [], []
    for s in BeautifulSoup(html, "lxml").find_all("script", type="application/ld+json"):
        raw = s.string or s.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            errors += 1
            continue
        stack = [data]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
            elif isinstance(n, dict):
                tt = n.get("@type")
                if tt:
                    types.extend(tt if isinstance(tt, list) else [tt])
                if "@id" in n:
                    ids.append(n["@id"])
                for k in ("datePublished", "dateModified"):
                    if k in n:
                        dates[k] = n[k]
                if "author" in n:
                    authors.append(str(n["author"])[:120])
                if "sameAs" in n:
                    sameas.extend(n["sameAs"] if isinstance(n["sameAs"], list) else [n["sameAs"]])
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
    out.update(jsonld_types=sorted(set(map(str, types))), jsonld_errors=errors, jsonld_ids=len(set(map(str, ids))),
               jsonld_dates=dates, jsonld_authors=authors[:3], sameas=sorted(set(map(str, sameas)))[:20])
    out["microdata"] = bool(re.search(r"itemscope", html))
    # social
    og = {m.get("property"): m.get("content") for m in soup.find_all("meta", property=re.compile("^og:"))}
    tw = {m.get("name"): m.get("content") for m in soup.find_all("meta", attrs={"name": re.compile("^twitter:")})}
    out["og"] = og
    out["twitter"] = tw
    # dates and authors in meta
    out["meta_dates"] = {m.get("property") or m.get("name"): m.get("content") for m in soup.find_all("meta")
                         if (m.get("property") or m.get("name") or "") in ("article:published_time", "article:modified_time", "og:updated_time", "last-modified")}
    ma = soup.find("meta", attrs={"name": "author"})
    out["meta_author"] = ma.get("content") if ma else None
    out["time_tags"] = len(soup.find_all("time"))
    # hreflang
    out["hreflang"] = [(l.get("hreflang"), l.get("href")) for l in soup.find_all("link", rel=lambda v: v and "alternate" in v) if l.get("hreflang")]
    # code health
    raw_soup = BeautifulSoup(html, "lxml")
    idlist = [t.get("id") for t in raw_soup.find_all(attrs={"id": True})]
    out["duplicate_ids"] = sum(c - 1 for c in collections.Counter(idlist).values() if c > 1)
    out["deprecated_tags"] = sum(len(raw_soup.find_all(t)) for t in DEPRECATED)
    out["inline_style_bytes"] = sum(len(s.get_text()) for s in raw_soup.find_all("style"))
    out["iframes"] = len(raw_soup.find_all("iframe"))
    out["scripts_external"] = len([s for s in raw_soup.find_all("script", src=True)])
    out["faq_signals"] = ("FAQPage" in out["jsonld_types"]) or bool(re.search(r"\bFAQs?\b|frequently asked", vis, re.I))
    return out


def url_issues(u):
    p = urlparse(u)
    path = p.path
    return {"url_len": len(u), "uppercase": path != path.lower(), "underscore": "_" in path,
            "params": bool(p.query), "double_slash": "//" in path, "non_ascii": any(ord(c) > 127 for c in u)}


def main(domain, max_pages, link_check):
    pre = load_json(domain, "preflight.json")
    if not pre:
        sys.exit("run 01_preflight.py first")
    origin = pre["canonical_origin"]
    host = urlparse(origin).netloc
    f = Fetcher()
    starts = [u for u, v in pre["sitemap_candidates"].items() if v["status"] == 200]
    maps, urls, off_host, multi = parse_sitemaps(f, starts, host)
    sm_out = {"sitemaps": maps, "url_count": len(urls), "off_host_urls": off_host[:50], "off_host_count": len(off_host),
              "in_multiple_sitemaps": len(multi), "in_multiple_examples": multi[:20],
              "lastmod_coverage": round(sum(1 for v in urls.values() if any(x["lastmod"] for x in v)) / max(1, len(urls)), 3)}
    save_json(domain, "sitemaps.json", sm_out)
    log(f"sitemaps: {len(maps)} files, {len(urls)} URLs")

    # sample by template (first path segment)
    groups = collections.defaultdict(list)
    for u in urls:
        if urlparse(u).netloc != host:
            continue
        seg = urlparse(u).path.strip("/").split("/")[0] or "(root)"
        groups[seg].append(u)
    sample = list(dict.fromkeys(pre["key_urls"].values()))
    per = max(2, math.ceil((max_pages - len(sample)) / max(1, len(groups))))
    rnd = random.Random(42)
    for seg, lst in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lst2 = sorted(lst, key=lambda x: max((y["lastmod"] or "" for y in urls[x]), default=""), reverse=True)
        pick = lst2[: per // 2] + rnd.sample(lst2[per // 2:], min(len(lst2[per // 2:]), per - per // 2))
        sample.extend(pick)
        if len(sample) >= max_pages:
            break
    sample = list(dict.fromkeys(sample))[:max_pages]
    log(f"crawling {len(sample)} URLs across {len(groups)} sitemap sections")

    pages, all_int, all_ext = [], collections.Counter(), collections.Counter()
    jl = (out_dir(domain) / "crawl.jsonl").open("w", encoding="utf-8")
    for i, u in enumerate(sample, 1):
        r = f.get(u)
        row = {"url": u, "status": r.get("status"), "final_url": r.get("final_url"),
               "hops": [h["status"] for h in r.get("history", [])], "ttfb_ms": r.get("ttfb_ms"),
               "challenge": detect_challenge(r), "in_sitemap": u in urls, "error": r.get("error"),
               "section": urlparse(u).path.strip("/").split("/")[0] or "(root)"}
        row.update(url_issues(u))
        if r.get("status") == 200 and "html" in r.get("headers", {}).get("content-type", ""):
            ex = extract(r, host)
            for l in ex.pop("_internal"):
                all_int[l] += 1
            for l in ex.pop("_external"):
                all_ext[l] += 1
            row.update(ex)
            if row.get("canonical"):
                row["canonical_is_self"] = row["canonical"].rstrip("/") == (r.get("final_url") or "").rstrip("/")
        pages.append(row)
        jl.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        if i % 25 == 0:
            log(f"  {i}/{len(sample)}")
    jl.close()

    # link check
    int_targets = [u for u, _ in all_int.most_common()][:link_check]
    ext_targets = [u for u, _ in all_ext.most_common()][: max(20, link_check // 3)]
    link_res = []
    for u in int_targets + ext_targets:
        r = f.get(u, method="HEAD")
        if r.get("status") in (403, 405, 501, None):
            r = f.get(u, max_bytes=100_000)
        link_res.append({"url": u, "internal": u in all_int, "status": r.get("status"),
                         "hops": len(r.get("history", [])), "final_url": r.get("final_url"),
                         "linked_from_pages": all_int.get(u) or all_ext.get(u)})
    save_json(domain, "links.json", {"checked": len(link_res), "results": link_res})

    ok = [p for p in pages if p.get("title") is not None]
    tc = collections.Counter(p["title"] for p in ok if p["title"])
    dc = collections.Counter(p["description"] for p in ok if p["description"])

    def cnt(fn):
        return sum(1 for p in ok if fn(p))

    def ex(fn, n=8):
        return [p["url"] for p in ok if fn(p)][:n]

    summ = {
        "pages_crawled": len(pages), "html_pages_parsed": len(ok),
        "status_counts": dict(collections.Counter(str(p["status"]) for p in pages)),
        "challenged": [p["url"] for p in pages if p["challenge"]][:20],
        "redirected_sitemap_urls": [p["url"] for p in pages if p["hops"] and p["in_sitemap"]][:20],
        "non200_sitemap_urls": [(p["url"], p["status"]) for p in pages if p["in_sitemap"] and p["status"] != 200][:20],
        "ttfb_ms_median": sorted([p["ttfb_ms"] for p in pages if p.get("ttfb_ms")])[len(pages) // 2] if pages else None,
        "checks": {
            "noindex_pages": {"n": cnt(lambda p: "noindex" in ((p.get("meta_robots") or "") + (p.get("x_robots_tag") or "")).lower()), "examples": ex(lambda p: "noindex" in ((p.get("meta_robots") or "") + (p.get("x_robots_tag") or "")).lower())},
            "missing_canonical": {"n": cnt(lambda p: p["canonical_count"] == 0), "examples": ex(lambda p: p["canonical_count"] == 0)},
            "multiple_canonical": {"n": cnt(lambda p: p["canonical_count"] > 1), "examples": ex(lambda p: p["canonical_count"] > 1)},
            "canonical_not_self": {"n": cnt(lambda p: p.get("canonical") and not p.get("canonical_is_self")), "examples": [(p["url"], p["canonical"]) for p in ok if p.get("canonical") and not p.get("canonical_is_self")][:8]},
            "missing_title": {"n": cnt(lambda p: not p["title"]), "examples": ex(lambda p: not p["title"])},
            "title_len_out_of_range_30_60": {"n": cnt(lambda p: p["title"] and not (30 <= p["title_len"] <= 60)), "examples": [(p["url"], p["title_len"]) for p in ok if p["title"] and not (30 <= p["title_len"] <= 60)][:8]},
            "duplicate_titles": {"n": sum(c for c in tc.values() if c > 1), "examples": [t for t, c in tc.most_common(5) if c > 1]},
            "missing_description": {"n": cnt(lambda p: not p["description"]), "examples": ex(lambda p: not p["description"])},
            "description_len_out_of_range_120_160": {"n": cnt(lambda p: p["description"] and not (120 <= p["description_len"] <= 160)), "examples": [(p["url"], p["description_len"]) for p in ok if p["description"] and not (120 <= p["description_len"] <= 160)][:8]},
            "duplicate_descriptions": {"n": sum(c for c in dc.values() if c > 1), "examples": [t[:90] for t, c in dc.most_common(5) if c > 1]},
            "h1_not_exactly_one": {"n": cnt(lambda p: p["h1_count"] != 1), "examples": [(p["url"], p["h1_count"]) for p in ok if p["h1_count"] != 1][:8]},
            "heading_level_skips": {"n": cnt(lambda p: p["heading_skips"] > 0), "examples": ex(lambda p: p["heading_skips"] > 0)},
            "empty_headings": {"n": cnt(lambda p: p["empty_headings"] > 0), "examples": ex(lambda p: p["empty_headings"] > 0)},
            "thin_under_250_words": {"n": cnt(lambda p: p["word_count"] < 250), "examples": [(p["url"], p["word_count"]) for p in ok if p["word_count"] < 250][:8]},
            "missing_lang": {"n": cnt(lambda p: not p["lang"]), "examples": ex(lambda p: not p["lang"])},
            "viewport_not_one": {"n": cnt(lambda p: p["viewport_count"] != 1), "examples": ex(lambda p: p["viewport_count"] != 1)},
            "charset_not_first": {"n": cnt(lambda p: not p["charset_first"]), "examples": ex(lambda p: not p["charset_first"])},
            "meta_in_body": {"n": cnt(lambda p: p["meta_in_body"] > 0), "examples": ex(lambda p: p["meta_in_body"] > 0)},
            "images_missing_alt": {"n": sum(p["img_missing_alt"] for p in ok), "pages": cnt(lambda p: p["img_missing_alt"] > 0), "examples": ex(lambda p: p["img_missing_alt"] > 0)},
            "images_without_dimensions": {"n": sum(p["img_no_dims"] for p in ok), "of_total": sum(p["images"] for p in ok)},
            "images_legacy_format": {"n": sum(p["img_legacy_format"] for p in ok), "of_total": sum(p["images"] for p in ok)},
            "mixed_content": {"n": cnt(lambda p: p["mixed_content"] > 0), "examples": ex(lambda p: p["mixed_content"] > 0)},
            "http_links": {"n": sum(p["http_links"] for p in ok), "pages": cnt(lambda p: p["http_links"] > 0), "examples": ex(lambda p: p["http_links"] > 0)},
            "internal_nofollow": {"n": sum(p["internal_nofollow"] for p in ok), "examples": ex(lambda p: p["internal_nofollow"] > 0)},
            "generic_anchors": {"n": sum(p["generic_anchors"] for p in ok), "pages": cnt(lambda p: p["generic_anchors"] > 0)},
            "over_100_links": {"n": cnt(lambda p: p["internal_links"] + p["external_links"] > 100), "examples": ex(lambda p: p["internal_links"] + p["external_links"] > 100)},
            "no_jsonld": {"n": cnt(lambda p: not p["jsonld_types"]), "examples": ex(lambda p: not p["jsonld_types"])},
            "jsonld_parse_errors": {"n": cnt(lambda p: p["jsonld_errors"] > 0), "examples": ex(lambda p: p["jsonld_errors"] > 0)},
            "jsonld_types_seen": dict(collections.Counter(t for p in ok for t in p["jsonld_types"]).most_common(30)),
            "og_incomplete": {"n": cnt(lambda p: not all(k in p["og"] for k in ("og:title", "og:description", "og:image", "og:url", "og:type"))), "examples": ex(lambda p: not all(k in p["og"] for k in ("og:title", "og:description", "og:image", "og:url", "og:type")))},
            "twitter_card_missing": {"n": cnt(lambda p: "twitter:card" not in p["twitter"]), "examples": ex(lambda p: "twitter:card" not in p["twitter"])},
            "no_main_landmark": {"n": cnt(lambda p: not p["landmarks"]["main"]), "examples": ex(lambda p: not p["landmarks"]["main"])},
            "h23_without_anchor_ids": {"n": sum(p["h23_total"] - p["h23_with_id"] for p in ok), "of_total": sum(p["h23_total"] for p in ok)},
            "pages_with_tables": cnt(lambda p: p["tables"] > 0),
            "pages_with_faq_signals": cnt(lambda p: p["faq_signals"]),
            "question_headings_total": sum(p["question_headings"] for p in ok),
            "h2_first_para_words_median_overall": sorted([p["h2_first_para_words_median"] for p in ok if p["h2_first_para_words_median"]])[len([1 for p in ok if p["h2_first_para_words_median"]]) // 2] if any(p["h2_first_para_words_median"] for p in ok) else None,
            "pages_with_visible_dates": cnt(lambda p: p["jsonld_dates"] or p["meta_dates"] or p["time_tags"]),
            "pages_with_author": cnt(lambda p: p["jsonld_authors"] or p["meta_author"]),
            "duplicate_ids": {"n": cnt(lambda p: p["duplicate_ids"] > 0), "examples": ex(lambda p: p["duplicate_ids"] > 0)},
            "deprecated_tags": {"n": cnt(lambda p: p["deprecated_tags"] > 0), "examples": ex(lambda p: p["deprecated_tags"] > 0)},
            "lorem_or_todo": {"n": cnt(lambda p: p["lorem_or_todo"]), "examples": ex(lambda p: p["lorem_or_todo"])},
            "html_over_100kb": {"n": cnt(lambda p: (p["html_bytes"] or 0) > 100_000), "examples": [(p["url"], p["html_bytes"]) for p in ok if (p["html_bytes"] or 0) > 100_000][:8]},
            "url_over_75_chars": {"n": sum(1 for p in pages if p["url_len"] > 75), "examples": [p["url"] for p in pages if p["url_len"] > 75][:8]},
            "url_uppercase_or_underscore": {"n": sum(1 for p in pages if p["uppercase"] or p["underscore"]), "examples": [p["url"] for p in pages if p["uppercase"] or p["underscore"]][:8]},
            "url_params": {"n": sum(1 for p in pages if p["params"]), "examples": [p["url"] for p in pages if p["params"]][:8]},
            "hreflang_pages": cnt(lambda p: p["hreflang"]),
            "sameas_seen": sorted({s for p in ok for s in p["sameas"]})[:30],
        },
        "links": {
            "internal_checked": sum(1 for l in link_res if l["internal"]),
            "external_checked": sum(1 for l in link_res if not l["internal"]),
            "internal_broken": [(l["url"], l["status"], l["linked_from_pages"]) for l in link_res if l["internal"] and (l["status"] or 0) >= 400][:30],
            "internal_redirecting": [(l["url"], l["final_url"]) for l in link_res if l["internal"] and l["hops"]][:30],
            "external_broken": [(l["url"], l["status"]) for l in link_res if not l["internal"] and (l["status"] or 0) >= 400][:30],
        },
    }
    p = save_json(domain, "crawl_summary.json", summ)
    log(f"OK crawl -> {p}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--max-pages", type=int, default=150)
    ap.add_argument("--link-check", type=int, default=300)
    a = ap.parse_args()
    main(normalize_domain(a.domain), a.max_pages, a.link_check)

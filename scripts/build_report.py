"""Validate out/<domain>/findings.json and build the client report.

Usage: python3 scripts/build_report.py example.com
Writes: out/<domain>/report/<domain>-technical-audit.html and summary.md
Exit code 1 with a list of problems if validation fails.
"""
import base64
import collections
import html
import io
import json
import math
import re
import sys

from common import KIT_DIR, OUT_ROOT, load_json, normalize_domain

VERDICTS = {"Pass": "pass", "Issue": "issue", "Needs client data": "need", "Not tested": "nt", "Not applicable": "na"}
SEVERITIES = ["Critical", "High", "Medium", "Low"]
HEDGES = re.compile(r"\b(may|might|possibly|could potentially|consider|perhaps|it seems)\b", re.I)
E = html.escape
REFS = {}


def catalogue_ids():
    ids = []
    for line in (KIT_DIR / "framework" / "checks.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([A-Z]{1,2}\d+)\s*\|", line)
        if m:
            ids.append(m.group(1))
    return ids


def walk_strings(o, path="$"):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_strings(v, f"{path}[{i}]")


def validate(fd):
    errors, warns = [], []
    for p, s in walk_strings(fd):
        if "—" in s and s.strip() != "—":
            errors.append(f"em dash in {p}: {s[:80]!r}")
    seen = collections.Counter()
    for sec in fd.get("sections", []):
        for c in sec.get("checks", []):
            cid = c.get("id", "?")
            seen[cid] += 1
            v = c.get("verdict")
            if v not in VERDICTS:
                errors.append(f"{cid}: verdict {v!r} not one of {list(VERDICTS)}")
                continue
            if v == "Pass" and not c.get("evidence"):
                errors.append(f"{cid}: Pass needs evidence")
            if v == "Issue":
                if c.get("severity") not in SEVERITIES:
                    errors.append(f"{cid}: Issue needs severity in {SEVERITIES}")
                for k in ("evidence", "impact", "fix"):
                    if not c.get(k):
                        errors.append(f"{cid}: Issue needs {k}")
            if v == "Needs client data" and not c.get("needs"):
                errors.append(f"{cid}: Needs client data requires 'needs'")
            if v in ("Not tested", "Not applicable") and not c.get("evidence"):
                errors.append(f"{cid}: {v} requires the reason in 'evidence'")
            if v in ("Pass", "Issue"):
                for k in ("evidence", "impact", "fix"):
                    if c.get(k) and HEDGES.search(c[k]):
                        warns.append(f"{cid}.{k}: hedging word '{HEDGES.search(c[k]).group(0)}', state it plainly")
    for cid, n in seen.items():
        if n > 1:
            errors.append(f"{cid}: appears {n} times")
    missing = [i for i in catalogue_ids() if i not in seen]
    if missing:
        errors.append(f"missing check IDs from framework/checks.md: {', '.join(missing)}")
    for k in ("domain", "client_name", "audit_date", "executive_summary", "sections", "actions"):
        if not fd.get(k):
            errors.append(f"top-level '{k}' missing")
    return errors, warns


def pill(text, cls):
    return f'<span class="pill {cls}">{E(text)}</span>'


# A trailing parenthetical naming evidence files or JSON fields, e.g.
# "(crawl_summary.checks.images_missing_alt)". Useful to the audit team and to
# a developer, meaningless to the client reading the sentence it sits in.
TRAILING_PAREN = re.compile(r"\s*\(([^()]{3,160})\)\s*(\.?)\s*$")


def split_source(text):
    """Return (prose, source_ref). The reference is shown as a quiet citation.

    Only a parenthetical made entirely of identifiers is pulled out. Every
    token has to carry a dot or an underscore, so "(links.json internal_broken)"
    is a citation while "(confirmed with a second client)" and "(help, docs,
    blog)" stay in the sentence where they carry meaning.
    """
    if not text:
        return "", ""
    m = TRAILING_PAREN.search(text)
    if not m:
        return text, ""
    tokens = [t for t in re.split(r"[,\s]+", m.group(1)) if t]
    if not tokens or not all("." in t or "_" in t for t in tokens):
        return text, ""
    prose = text[: m.start()].rstrip()
    if m.group(2):                      # the sentence keeps its full stop
        prose += "."
    return prose, m.group(1)


URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")


def linkify(text):
    """Escape prose and turn every address in it into a link you can click.

    The escaping happens per fragment rather than up front, because escaping
    first turns a quote into &quot; and the address pattern then swallows the
    entity along with it.

    Trailing punctuation is left outside the link, so "ends at
    https://example.com/about." does not link to the full stop.
    """
    out, last = [], 0
    for m in URL_IN_TEXT.finditer(text or ""):
        url, tail = m.group(0), ""
        while url and url[-1] in ".,;:)]":
            tail = url[-1] + tail
            url = url[:-1]
        out.append(E(text[last:m.start()]))
        if url:
            eu = E(url)
            out.append(f'<a class="u" href="{eu}" target="_blank" rel="noopener">{eu}</a>')
        out.append(E(tail))
        last = m.end()
    out.append(E((text or "")[last:]))
    return "".join(out)


def evidence_html(text):
    prose, src = split_source(text)
    out = linkify(prose)
    if src:
        out += f'<span class="src" title="Evidence file">{E(src)}</span>'
    return out


def crawler_count(domain):
    """How many crawler user agents were actually tested, from the evidence."""
    ca = load_json(domain, "crawler_access.json") or {}
    return len(ca.get("agents", [])) or ""


def font_face_css():
    """Inline Parkinsans as base64.

    The design system allows one typeface and loads it from Google Fonts. A
    client report has to render identically from an email attachment or a
    network that blocks outbound requests, so the two variable subsets ship
    inside the file instead. latin-ext is included because a Turkish client's
    report needs the characters it carries.
    """
    out = []
    for name, rng in (
        ("pk-latin.woff2",
         "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
         "U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, "
         "U+2212, U+2215, U+FEFF, U+FFFD"),
        ("pk-latinext.woff2",
         "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, "
         "U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, "
         "U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF"),
    ):
        path = KIT_DIR / "templates" / "fonts" / name
        if not path.is_file():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
        out.append("@font-face{font-family:'Parkinsans';font-style:normal;"
                   "font-weight:300 800;font-display:swap;"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
                   f"unicode-range:{rng};}}")
    return "\n".join(out)


def load_references():
    """check ID -> [{publisher, title, url}], from framework/references.json."""
    path = KIT_DIR / "framework" / "references.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources", {})
    return {cid: [sources[k] for k in keys if k in sources]
            for cid, keys in data.get("checks", {}).items()}


def reference_html(refs):
    """The standards a finding rests on, linked, under the fix."""
    if not refs:
        return ""
    links = " ".join(
        f'<a class="ref" href="{E(r["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{E(r["publisher"])}: {E(r["title"])}</a>' for r in refs)
    return f'<div class="refs"><span class="refs-label">Reference</span>{links}</div>'


def screenshot_section(domain):
    """Desktop and mobile captures, downscaled and inlined so the report is one file."""
    shots = OUT_ROOT / domain / "data" / "shots"
    if not shots.is_dir():
        return "", 0
    try:
        from PIL import Image
    except ImportError:
        return "", 0
    cards = []
    for desktop in sorted(shots.glob("desktop-*.png"))[:6]:
        mobile = shots / desktop.name.replace("desktop-", "mobile-", 1)
        pair = []
        for path, device, dims, width in ((desktop, "Desktop", "1366 x 900", 900),
                                          (mobile, "Mobile", "390 x 844", 300)):
            label = f"{device} {dims}"
            if not path.is_file():
                continue
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((width, width * 4), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=78, optimize=True)
            except Exception:  # noqa: BLE001
                continue
            b64 = base64.b64encode(buf.getvalue()).decode()
            pair.append(
                f'<figure class="shot shot-{device.lower()}">'
                f'<figcaption class="devcap"><span class="dev">{E(device)}</span>'
                f'<span class="dim">{E(dims)}</span></figcaption>'
                f'<img alt="{E(label)} capture" src="data:image/jpeg;base64,{b64}"></figure>')
        if pair:
            slug = desktop.stem[len("desktop-"):]
            cards.append(f'<div class="shotrow"><h3>{E(slug_to_url(domain, slug))}</h3>'
                         f'<div class="shots">{"".join(pair)}</div></div>')
    return "".join(cards), len(cards)


# Status colours, the same ones the stacked bar uses, so a reader who learns the
# legend once can read every chart in the report.
HIDDEN_SECTIONS = {"L"}      # rendered nowhere, so nothing may link to them
C_PASS, C_CRIT, C_HIGH = "#10B981", "#9F1239", "#E11D48"
C_MED, C_LOW, C_NEED, C_NT = "#D97706", "#94A3B8", "#F59E0B", "#CBD5E1"


def donut(segments, size=140, stroke=18, centre=None, sub=None):
    """An SVG ring chart. No script, no library: it has to render with
    JavaScript off and survive being printed."""
    total = sum(v for _, v, _ in segments) or 1
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    off, parts = 0.0, []
    for label, v, col in segments:
        if not v:
            continue
        frac = v / total
        parts.append(
            f'<circle cx="{size/2}" cy="{size/2}" r="{r:.2f}" fill="none" stroke="{col}" '
            f'stroke-width="{stroke}" stroke-dasharray="{circ*frac:.2f} {circ:.2f}" '
            f'stroke-dashoffset="{-circ*off:.2f}" transform="rotate(-90 {size/2} {size/2})">'
            f'<title>{E(label)}: {v}</title></circle>')
        off += frac
    mid = ""
    if centre is not None:
        mid = (f'<text x="{size/2}" y="{size/2 - (2 if sub else -6)}" class="dnum" '
               f'text-anchor="middle">{E(str(centre))}</text>')
        if sub:
            mid += (f'<text x="{size/2}" y="{size/2 + 20}" class="dsub" '
                    f'text-anchor="middle">{E(sub)}</text>')
    return (f'<svg class="donut" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'role="img" aria-hidden="true">{"".join(parts)}{mid}</svg>')


def overview_section(domain, fd, allc, vc, sc):
    """A dashboard of the whole audit, where every bar is a link to the detail.

    The counts and the stacked bar told a reader how much was wrong but not
    where, so finding the worst area meant scrolling 18 sections. Each row here
    jumps straight to the section it names.
    """
    issues = vc["Issue"]
    judged = vc["Pass"] + issues
    score = round(100 * vc["Pass"] / judged) if judged else 0
    band = "Good" if score >= 80 else "Fair" if score >= 50 else "Poor"
    bandcls = "is-ok" if score >= 80 else "is-warn" if score >= 50 else "is-bad"

    health = (f'<div class="ocard"><h3>Health score</h3>'
              f'{donut([("Passing", vc["Pass"], C_PASS), ("Issues", issues, C_HIGH)], centre=score, sub=band)}'
              f'<p class="onote">{vc["Pass"]} of {judged} checks that could be judged are '
              f'passing. <span class="{bandcls}">{E(band)}</span></p></div>')

    verd = [("Pass", vc["Pass"], C_PASS, "pass"), ("Issues", issues, C_HIGH, "issue"),
            ("Needs client data", vc["Needs client data"], C_NEED, "need"),
            ("Not tested", vc["Not tested"], C_NT, "nt"),
            ("Not applicable", vc["Not applicable"], C_LOW, "na")]
    vkeys = "".join(
        f'<li><a href="#detail" data-filter="{k}"><i style="background:{c}"></i>'
        f'<span>{E(l)}</span><b>{n}</b></a></li>'
        for l, n, c, k in verd if n)
    verdict = (f'<div class="ocard"><h3>Every check</h3>'
               f'{donut([(l, n, c) for l, n, c, _ in verd], centre=len(allc), sub="checks")}'
               f'<ul class="okeys">{vkeys}</ul></div>')

    sevs = [("Critical", sc["Critical"], C_CRIT), ("High", sc["High"], C_HIGH),
            ("Medium", sc["Medium"], C_MED), ("Low", sc["Low"], C_LOW)]
    smax = max([n for _, n, _ in sevs] + [1])
    srows = "".join(
        f'<li><a href="#detail" data-filter="{l.lower()}"><span class="olab">{E(l)}</span>'
        f'<span class="otrack"><i style="width:{n/smax*100:.1f}%;background:{c}"></i></span>'
        f'<b>{n}</b></a></li>' for l, n, c in sevs if n)
    sev = (f'<div class="ocard ocard-wide"><h3>Issues by severity</h3>'
           f'<ul class="obars">{srows}</ul></div>')

    # Where the issues actually are. This is the part that saves the scrolling.
    rows = []
    for sec_ in fd["sections"]:
        if sec_["id"] in HIDDEN_SECTIONS:
            continue
        n = sum(1 for c in sec_["checks"] if c["verdict"] == "Issue")
        urgent = sum(1 for c in sec_["checks"]
                     if c["verdict"] == "Issue" and c.get("severity") in ("Critical", "High"))
        if n:
            rows.append((n, urgent, sec_["id"], sec_["title"]))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    amax = max([r[0] for r in rows] + [1])
    arows = "".join(
        f'<li><a href="#s-{sid.lower()}"><span class="olab">{E(title)}</span>'
        f'<span class="otrack"><i style="width:{n/amax*100:.1f}%;background:'
        f'{C_HIGH if urgent else C_MED}"></i></span><b>{n}</b>'
        f'<em>{f"{urgent} urgent" if urgent else ""}</em></a></li>'
        for n, urgent, sid, title in rows)
    areas = (f'<div class="ocard ocard-wide"><h3>Where the issues are</h3>'
             f'<p class="onote">Every row opens that section.</p>'
             f'<ul class="obars obars-link">{arows}</ul></div>')

    status = ""
    counts = collections.Counter()
    seen = {}
    jl = OUT_ROOT / domain / "data" / "crawl.jsonl"
    if jl.is_file():
        for line in jl.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("url") and r.get("status"):
                seen[r["url"]] = r["status"]
    for url, r in (load_json(domain, "pages_summary.json") or {}).items():
        if r.get("status"):
            seen[url] = r["status"]
    for st in seen.values():
        counts[f"{str(st)[0]}xx"] += 1
    if counts:
        order = [("2xx", C_PASS), ("3xx", C_MED), ("4xx", C_HIGH), ("5xx", C_CRIT)]
        segs = [(f"{k} responses", counts.get(k, 0), c) for k, c in order]
        keys = "".join(f'<li><i style="background:{c}"></i><span>{k}</span>'
                       f'<b>{counts.get(k, 0)}</b></li>' for k, c in order if counts.get(k))
        status = (f'<div class="ocard"><h3>Crawled URL status</h3>'
                  f'{donut(segs, centre=sum(counts.values()), sub="URLs")}'
                  f'<ul class="okeys">{keys}</ul></div>')

    return f'<div class="ogrid">{health}{verdict}{status}{sev}{areas}</div>'


CTA_URL = "https://calendly.com/technical-audit-by-wellows/website-audit"


def cta_panel(heading, line):
    """An in-page booking panel, the same link as the one in the bar.

    Built as a panel rather than a bare button so it reads as an offer in the
    flow of the report instead of a stray control, and it keeps the sanctioned
    blue surface rather than inventing a tint.
    """
    return (f'<div class="ctapanel"><div><h3>{E(heading)}</h3><p>{E(line)}</p></div>'
            f'<a class="cta cta-panel" href="{CTA_URL}" target="_blank" rel="noopener noreferrer">'
            f'Schedule Your Free Audit Call</a></div>')


def crawled_section(domain, fd):
    """The list of pages the audit actually read, with status, title and size.

    A client asked which URLs were checked, and the honest answer has to come
    from the evidence rather than from the method note, which is why this reads
    crawl.jsonl and the saved page set rather than anything hand written.
    """
    rows = {}
    for line in (OUT_ROOT / domain / "data" / "crawl.jsonl").read_text(
            encoding="utf-8").splitlines() if (OUT_ROOT / domain / "data" / "crawl.jsonl").is_file() else []:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("url"):
            rows[r["url"]] = {"status": r.get("status"), "title": r.get("title"),
                              "words": r.get("word_count")}
    pages = load_json(domain, "pages_summary.json") or {}
    for url, r in pages.items():
        keep = rows.get(url) or {}
        rows[url] = {"status": r.get("status") or keep.get("status"),
                     "title": r.get("title") or keep.get("title"),
                     "words": r.get("words") or keep.get("words")}
    rows = {u: r for u, r in rows.items() if r.get("status")}
    if not rows:
        return "", 0
    out = []
    for url in sorted(rows):
        r = rows[url]
        st = str(r.get("status") or "")
        cls = "is-ok" if st == "200" else "is-bad"
        words = f'{r["words"]:,} words' if r.get("words") else ""
        out.append(f'<tr><td><a class="u" href="{E(url)}" target="_blank" rel="noopener">'
                   f'{E(url)}</a></td><td><span class="pill {cls}">{E(st)}</span></td>'
                   f'<td>{E(r.get("title") or "")}</td><td class="num">{E(words)}</td></tr>')
    return (f'<table class="checks"><thead><tr><th>URL</th><th>Status</th><th>Title</th>'
            f'<th class="num">Length</th></tr></thead><tbody>{"".join(out)}</tbody></table>',
            len(rows))


def js_section(domain):
    """The same page with JavaScript on and off, full height, side by side.

    M1 reports this as a ratio, and a ratio is not an argument. The pair of
    pictures is: whatever is missing from the right-hand image is what a crawler
    that does not run JavaScript never sees.
    """
    shots = OUT_ROOT / domain / "data" / "shots"
    if not shots.is_dir():
        return "", 0
    try:
        from PIL import Image
    except ImportError:
        return "", 0
    rendered = (load_json(domain, "render.json") or {}).get("pages", {})
    cards = []
    for on in sorted(shots.glob("js-on-*.png"))[:4]:
        off = shots / on.name.replace("js-on-", "js-off-", 1)
        if not off.is_file():
            continue
        slug = on.stem[len("js-on-"):]
        pair = []
        for path, label in ((on, "JavaScript on"), (off, "JavaScript off")):
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((620, 4200), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=74, optimize=True)
            except Exception:  # noqa: BLE001
                continue
            b64 = base64.b64encode(buf.getvalue()).decode()
            pair.append(f'<figure class="shot shot-js">'
                        f'<figcaption class="devcap"><span class="dev">{E(label)}</span></figcaption>'
                        f'<img alt="{E(label)} full page capture" '
                        f'src="data:image/jpeg;base64,{b64}"></figure>')
        if len(pair) != 2:
            continue
        url = slug_to_url(domain, slug)
        note = ""
        for u, e in rendered.items():
            if re.sub(r"[^a-z0-9]+", "-", u.lower())[-60:] == slug and e.get("js_parity"):
                jp = e["js_parity"]
                note = (f'<p class="jsnote">With JavaScript switched off this page keeps '
                        f'{int(jp["words_share"] * 100)} percent of its words and '
                        f'{int(jp["links_share"] * 100)} percent of its links, and the main '
                        f'heading is {"the same" if jp["h1_same"] else "different"}.</p>')
                break
        cards.append(f'<div class="shotrow"><h3>{E(url)}</h3>{note}'
                     f'<div class="shots">{"".join(pair)}</div></div>')
    return "".join(cards), len(cards)


def slug_to_url(domain, slug):
    """06_render.py names a capture after a slug of its URL; recover the URL."""
    rendered = (load_json(domain, "render.json") or {}).get("pages", {})
    for u in rendered:
        if re.sub(r"[^a-z0-9]+", "-", u.lower())[-60:] == slug:
            return u.replace("https://", "").replace("http://", "").rstrip("/") or domain
    return domain


def agent_matrix(domain):
    ca = load_json(domain, "crawler_access.json")
    if not ca:
        return "<p>Crawler access data not collected.</p>"
    keys = list(ca["key_urls"].keys())
    rows = []
    for a in ca["agents"]:
        rb = a["summary"]["robots_blocked_on"]
        fb = a["summary"]["fetch_blocked_on"]
        sm = a["summary"]["much_smaller_than_chrome_on"]
        robots_cell = '<span class="ok">Allowed</span>' if not rb else f'<span class="bad">Blocked on {E(", ".join(rb))}</span>'
        if a["fetch"]:
            home = a["fetch"].get("home") or next(iter(a["fetch"].values()))
            st = home.get("status")
            fetch_cell = (f'<span class="ok">{st} on all {len(a["fetch"])}</span>' if not fb
                          else f'<span class="bad">Blocked on {E(", ".join(fb))}</span>')
            ch = "; ".join(sorted({v["challenge"] for v in a["fetch"].values() if v.get("challenge")})) or "None"
            size = f'{home.get("size_vs_chrome")}' if home.get("size_vs_chrome") is not None else "n/a"
            if sm:
                size += f' <span class="bad">(under 0.8 on {E(", ".join(sm))})</span>'
            opt = sorted({k for v in a["fetch"].values() for k in (v.get("meta_optout") or {})} |
                         ({"X-Robots-Tag"} if any(v.get("x_robots_optout") for v in a["fetch"].values()) else set()))
            opt_cell = '<span class="bad">' + E(", ".join(opt)) + "</span>" if opt else "None"
        else:
            fetch_cell, ch, size, opt_cell = "Control token (no crawler)", "n/a", "n/a", "n/a"
        rows.append(f"<tr><td class='ck'>{E(a['name'])}</td><td>{E(a['operator'])}</td><td>{E(a['type'])}</td>"
                    f"<td>{E(a['powers'])}</td><td>{robots_cell}<br><small>group: {E(str(a['robots_group']))}</small></td>"
                    f"<td>{fetch_cell}</td><td>{E(ch)}</td><td>{size}</td><td>{opt_cell}</td></tr>")
    head = ("<tr><th>Agent</th><th>Operator</th><th>Type</th><th>Powers</th><th>robots.txt</th>"
            f"<th>HTTP ({len(keys)} key URLs)</th><th>Challenge</th><th>Size vs Chrome (home)</th><th>Opt-out signals</th></tr>")
    urls = "".join(f"<li><b>{E(k)}</b>: <code>{E(u)}</code></li>" for k, u in ca["key_urls"].items())
    deps = json.loads((KIT_DIR / "framework" / "agents.json").read_text())["engine_dependencies"]
    drows = "".join(f"<tr><td class='ck'>{E(d['engine'])}</td><td>{E(d['reads_through'])}</td><td>{E(d['must_allow'])}</td></tr>" for d in deps)
    return (f"<p class='intro'>Key URLs tested:</p><ul class='intro'>{urls}</ul>"
            f"<div class='table-wrap'><table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table></div>"
            f"<p class='intro'>{E(ca.get('method_note', ''))}</p>"
            "<p class='intro'><b>Which AI engine depends on which crawler.</b> Blocking a crawler hides the site from every engine on its row.</p>"
            f"<div class='table-wrap'><table><thead><tr><th>AI engine</th><th>Reads the web through</th><th>Must allow</th></tr></thead><tbody>{drows}</tbody></table></div>")


def build(domain):
    global REFS
    REFS = load_references()
    fd = load_json(domain, "../findings.json")
    if fd is None:
        sys.exit(f"out/{domain}/findings.json not found")
    errors, warns = validate(fd)
    for w in warns:
        print("WARN ", w)
    if errors:
        for e in errors:
            print("ERROR", e)
        sys.exit(1)

    shown = [s for s in fd["sections"] if s["id"] not in HIDDEN_SECTIONS]
    allc = [c for s in shown for c in s["checks"]]
    vc = collections.Counter(c["verdict"] for c in allc)
    sc = collections.Counter(c.get("severity") for c in allc if c["verdict"] == "Issue")
    # One stacked bar of the whole audit, with a legend under it. Reads at a
    # glance in a way six separate number tiles did not.
    bands = [("pass", vc["Pass"], "Pass"), ("crit", sc["Critical"], "Critical"),
             ("high", sc["High"], "High"), ("med", sc["Medium"], "Medium"),
             ("low", sc["Low"], "Low"), ("need", vc["Needs client data"], "Needs data"),
             ("nt", vc["Not tested"], "Not tested"),
             ("na", vc["Not applicable"], "Not applicable")]
    bands = [b for b in bands if b[1]]
    total = sum(n for _, n, _ in bands) or 1
    segs = "".join(f'<span class="seg b-{c}" style="width:{n / total * 100:.4f}%" '
                   f'title="{E(l)}: {n}"></span>' for c, n, l in bands)
    keys = "".join(f'<span class="key"><i class="b-{c}"></i>{E(l)} <b>{n}</b></span>'
                   for c, n, l in bands)
    tiles_html = f'<div class="bar" role="img" aria-label="{E(", ".join(f"{l} {n}" for _, n, l in bands))}">{segs}</div><div class="keys">{keys}</div>'

    es = fd["executive_summary"]
    body, toc = [], []
    # Each top issue carries its severity and a link straight to the check,
    # so the reader can judge and jump without scrolling the appendix.
    by_id = {c["id"]: c for c in allc}
    tops = []
    for t in es.get("top_issues", []):
        src = by_id.get(t["id"], {})
        sev = src.get("severity", "")
        badge = pill(f"{sev} issue", "s-" + sev.lower()) if sev else ""
        tops.append(
            f'<li><div class="tophead"><b>{E(t["title"])}</b>{badge}'
            f'<a class="jump chk" href="#c-{E(t["id"])}">Check {E(t["id"])}</a></div>'
            f'<span>{E(src.get("evidence", ""))}</span>'
            f'<span class="fixline"><b>Fix:</b> {E(t["fix"])}</span></li>')
    top = "".join(tops)
    paras = "".join(f"<p>{E(p)}</p>" for p in es.get("paragraphs", []))
    # Key figures sit beside the narrative. Every one is measured, not derived
    # from an estimate, so the panel can be read on its own.
    issues_total = vc["Issue"]
    urgent = sc["Critical"] + sc["High"]
    glance = [("Checks run", len(allc), ""),
              ("Passing", vc["Pass"], "is-ok"),
              ("Issues found", issues_total, "is-bad" if issues_total else ""),
              ("Critical and High", urgent, "is-bad" if urgent else "is-ok"),
              ("Pages crawled", meth_pages := fd.get("method", {}).get("pages_crawled", ""), ""),
              ("Crawlers tested", crawler_count(domain), "")]
    glance_html = "".join(
        f'<div><dt>{E(label)}</dt><dd class="{cls}">{E(str(val))}</dd></div>'
        for label, val, cls in glance if val != "")
    # The reader's first question is what the audit covered, so the summary says
    # how many pages were read and links straight to the list.
    crawled_html, n_crawled = crawled_section(domain, fd)
    scope = ""
    if n_crawled:
        scope = (f'<p class="scope">This audit read <b>{n_crawled}</b> '
                 f'{"page" if n_crawled == 1 else "pages"} of {E(domain)}. '
                 f'<a href="#crawled">See every URL that was checked</a>.</p>')
    # The charts open the report. The executive summary, its At a glance panel
    # and the top-issue list were all restating counts the Overview now draws.
    body.append('<section class="sec" id="overview" data-title="Overview">'
                '<h2>Overview</h2><p class="lede">The whole audit at a glance. '
                'Every bar below is a link: click it to open the checks it counts.</p>'
                + overview_section(domain, fd, allc, vc, sc) + scope
                + cta_panel("Want these fixed?",
                            "Book a call and we will walk through the findings with your "
                            "developer and agree what gets done first.")
                + '</section>')
    toc.append(("overview", "", "Overview", 0))
    if crawled_html:
        body.append(f'<section class="sec" id="crawled" data-title="Crawled URLs">'
                    f'<h2>Crawled URLs</h2><p class="lede">Every page this audit read, with the '
                    f'status it returned. Each address opens in a new tab.</p>'
                    f'{crawled_html}</section>')
        toc.append(("crawled", "", "Crawled URLs", n_crawled))

    # Client reading order: what to do, then the evidence, then the detail.
    # The full check tables and the method notes are reference material and sit
    # behind the decisions they support.
    pcls = {"P0": "p-p0", "P1": "p-p1", "P2": "p-p2"}

    def check_links(spec):
        """"AI5, AI11" becomes two links straight to those rows."""
        ids = [s.strip() for s in str(spec or "").split(",") if s.strip()]
        return " ".join(f'<a class="jump" href="#c-{E(i)}">{E(i)}</a>' for i in ids)

    arows = "".join(f'<tr><td>{pill(a["priority"], pcls.get(a["priority"], "p-p2"))}</td>'
                    f'<td class="ck">{E(a["action"])}</td>'
                    f'<td class="id">{check_links(a.get("checks"))}</td>'
                    f'<td>{E(a.get("owner", ""))}</td></tr>'
                    for a in sorted(fd["actions"], key=lambda a: a["priority"]))

    js_html, n_js = js_section(domain)
    if js_html:
        body.append('<section class="sec" id="js" data-title="With and without JavaScript">'
                    '<h2>With and without JavaScript</h2>'
                    '<p class="intro">The same page captured twice at full height: once in a '
                    'browser running JavaScript, and once with JavaScript switched off. '
                    'Whatever is missing from the second image is what a crawler that does not '
                    'run JavaScript never sees.</p>'
                    f'{js_html}</section>')
        toc.append(("js", "", "With and without JavaScript", n_js))

    well = "".join(f"<li>{E(w)}</li>" for w in fd.get("working_well", []))
    body.append(f'<section class="sec" id="well" data-title="What is working well"><h2>What is already working</h2>'
                f'<p class="intro">Measured and passing. These need no attention.</p>'
                f'<ul class="well">{well}</ul></section>')
    toc.append(("well", "", "What is already working", 0))

    body.append('<section class="sec appendix-open" id="detail" data-title="Every check in full">'
                '<h2>Every check in full</h2>'
                f'<p class="intro">All {len(allc)} checks, grouped by area, each with the measured value and '
                'the exact fix. Use the filters above to narrow this to issues only.</p></section>')
    toc.append(("detail", "", "Every check in full", 0))

    for s in fd["sections"]:
        if s["id"] in HIDDEN_SECTIONS:
            continue
        sid = "s-" + s["id"].lower()
        n_issue = sum(1 for c in s["checks"] if c["verdict"] == "Issue")
        rows = []
        for c in s["checks"]:
            v = VERDICTS[c["verdict"]]
            sev = (c.get("severity") or "").lower()
            vcell = pill(c["verdict"], "v-" + v) + (" " + pill(c["severity"], "s-" + sev) if c["verdict"] == "Issue" else "")
            ev = evidence_html(c.get("evidence", ""))
            if c["verdict"] == "Needs client data":
                ev = (ev + "<br>" if ev else "") + "<b>Data needed:</b> " + linkify(c.get("needs", ""))
            fx = ""
            if c["verdict"] == "Issue":
                fx = (f"<span class='imp'><b>Impact:</b> {linkify(c['impact'])}</span>"
                      f"{linkify(c['fix'])}")
            elif c["verdict"] == "Pass":
                fx = linkify(c.get("fix") or "No change needed.")
            else:
                fx = linkify(c.get("fix", ""))
            # Every check is its own anchor, so the summary, the action plan
            # and a pasted link all land on the exact row.
            anchor = "c-" + c["id"]
            fx += reference_html(REFS.get(c["id"], []))
            rows.append(f'<tr id="{anchor}" data-v="{v}" data-s="{sev}">'
                        f'<td class="id"><a class="anchor" href="#{anchor}" '
                        f'title="Link to this check">{E(c["id"])}</a></td>'
                        f'<td class="ck">{E(c["check"])}</td>'
                        f'<td>{vcell}</td><td class="ev">{ev}</td><td class="fx">{fx}</td></tr>')
        extra = agent_matrix(domain) if s["id"] == "AI" else ""
        # data-checks marks the sections the Show filter governs. Everything
        # else (summary, plan, captures, method) is narrative and is stepped
        # out of the way when a filter is on, rather than left behind looking
        # like a result.
        body.append(f'<section class="sec" id="{sid}" data-checks="1" data-title="{E(s["title"])}"><h2><span class="secnum">{E(s["id"])}</span>{E(s["title"])}</h2>'
                    f'<p class="intro">{E(s.get("intro", ""))}</p>'
                    '<div class="table-wrap"><table><thead><tr><th>ID</th><th>Check</th><th>Verdict</th><th>Evidence</th><th>Fix</th></tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table></div>{extra}</section>')
        toc.append((sid, s["id"], s["title"], n_issue))

    meth = fd.get("method", {})
    notes = "".join(f"<li>{E(n)}</li>" for n in meth.get("notes", []))
    body.append('<section class="sec" id="talk" data-title="Talk to us">'
                + cta_panel("That is the whole audit",
                            "Bring this report to a call and we will prioritise the fixes "
                            "against your own goals, at no charge.")
                + '</section>')
    toc.append(("talk", "", "Talk to us", 0))
    if fd.get("prompt_set"):
        ps = "".join(f"<li>{E(p)}</li>" for p in fd["prompt_set"])
        body.append(f'<section class="sec" id="prompts" data-title="Prompts to track"><h2>Prompts to track in Wellows</h2><ol>{ps}</ol></section>')
        toc.append(("prompts", "", "Prompts to track", 0))

    toc_html = "".join(f'<li><a href="#{i}" data-t="{i}"><span class="n">{E(n)}</span><span>{E(t)}</span>'
                       f'<span class="c">{c if c else ""}</span></a></li>' for i, n, t, c in toc)
    urgent_n = sc["Critical"] + sc["High"]
    chips = [("all", "All checks", len(allc)),
             ("issue", "Issues found", vc["Issue"]),
             ("urgent", "Fix first: Critical and High", urgent_n),
             ("pass", "Passing, no action needed", vc["Pass"]),
             ("need", "Needs data from you", vc["Needs client data"])]
    filters_html = "".join(
        f'<button class="chip" data-f="{k}" aria-pressed="{"true" if k == "all" else "false"}">'
        f'{E(label)} <b>{n}</b></button>' for k, label, n in chips)

    tpl = (KIT_DIR / "templates" / "report.html").read_text(encoding="utf-8")
    client = fd["client_name"]
    out = (tpl.replace("%%FONTS%%", font_face_css())
              .replace("%%TITLE%%", E(f"{client} Technical Audit"))
              .replace("%%DATE%%", E(fd["audit_date"]))
              .replace("%%H1%%", f"Can every search and AI engine reach <em>{E(fd['domain'])}</em>?")
              .replace("%%HEADLINE%%", E(es["headline"]))
              .replace("%%TILES%%", tiles_html).replace("%%TOC%%", toc_html)
              .replace("%%FILTERS%%", filters_html)
              .replace("%%BODY%%", "\n".join(body)).replace("%%CLIENT%%", E(client)))
    rd = OUT_ROOT / domain / "report"
    rd.mkdir(parents=True, exist_ok=True)
    path = rd / f"{domain}-technical-audit.html"
    path.write_text(out, encoding="utf-8")
    md = [f"# {client}: technical audit summary ({fd['audit_date']})", "", es["headline"], "",
          f"Checks: {len(allc)}. Pass {vc['Pass']}. Issues {vc['Issue']} (Critical {sc['Critical']}, High {sc['High']}, Medium {sc['Medium']}, Low {sc['Low']}). "
          f"Needs client data {vc['Needs client data']}. Not tested {vc['Not tested']}. Not applicable {vc['Not applicable']}.", "", "## Top issues"]
    md += [f"{i}. {t['id']}: {t['title']}. Fix: {t['fix']}" for i, t in enumerate(es.get("top_issues", []), 1)]
    (rd / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"OK report -> {path}")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: build_report.py <domain>")
    build(normalize_domain(sys.argv[1]))

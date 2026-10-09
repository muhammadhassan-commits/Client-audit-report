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
import re
import sys

from common import KIT_DIR, OUT_ROOT, load_json, normalize_domain

VERDICTS = {"Pass": "pass", "Issue": "issue", "Needs client data": "need", "Not tested": "nt", "Not applicable": "na"}
SEVERITIES = ["Critical", "High", "Medium", "Low"]
HEDGES = re.compile(r"\b(may|might|possibly|could potentially|consider|perhaps|it seems)\b", re.I)
E = html.escape


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


def evidence_html(text):
    prose, src = split_source(text)
    out = E(prose)
    if src:
        out += f'<span class="src" title="Evidence file">{E(src)}</span>'
    return out


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
        for path, label, width in ((desktop, "Desktop 1366x900", 900),
                                   (mobile, "Mobile 390x844", 300)):
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
            pair.append(f'<figure class="shot"><img alt="{E(label)} capture" '
                        f'src="data:image/jpeg;base64,{b64}"><figcaption>{E(label)}</figcaption></figure>')
        if pair:
            slug = desktop.stem[len("desktop-"):]
            cards.append(f'<div class="shotrow"><h3>{E(slug_to_url(domain, slug))}</h3>'
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

    allc = [c for s in fd["sections"] for c in s["checks"]]
    vc = collections.Counter(c["verdict"] for c in allc)
    sc = collections.Counter(c.get("severity") for c in allc if c["verdict"] == "Issue")
    tiles = [("pass", vc["Pass"], "Passing"), ("crit", sc["Critical"], "Critical issues"), ("high", sc["High"], "High issues"),
             ("", sc["Medium"] + sc["Low"], "Medium and low issues"), ("need", vc["Needs client data"], "Need client data"),
             ("", vc["Not tested"] + vc["Not applicable"], "Not tested or N/A")]
    tiles_html = "".join(f'<div class="tile {c}"><b>{n}</b><span>{E(l)}</span></div>' for c, n, l in tiles)

    es = fd["executive_summary"]
    body, toc = [], []
    top = "".join(f"<li><b>{E(t['id'])}: {E(t['title'])}</b><span>{E(t['fix'])}</span></li>" for t in es.get("top_issues", []))
    paras = "".join(f"<p>{E(p)}</p>" for p in es.get("paragraphs", []))
    body.append(f'<section class="sec" id="summary" data-title="Executive summary"><h2>Executive summary</h2>{paras}'
                f'<h3>Top issues to fix first</h3><ol class="top">{top}</ol></section>')
    toc.append(('summary', '', 'Executive summary', 0))

    # Client reading order: what to do, then the evidence, then the detail.
    # The full check tables and the method notes are reference material and sit
    # behind the decisions they support.
    pcls = {"P0": "p-p0", "P1": "p-p1", "P2": "p-p2"}
    arows = "".join(f'<tr><td>{pill(a["priority"], pcls.get(a["priority"], "p-p2"))}</td><td class="ck">{E(a["action"])}</td>'
                    f'<td class="id">{E(a.get("checks", ""))}</td><td>{E(a.get("owner", ""))}</td><td>{E(a.get("effort", ""))}</td></tr>'
                    for a in sorted(fd["actions"], key=lambda a: a["priority"]))
    body.append('<section class="sec" id="plan" data-title="What to do, in order"><h2>What to do, in order</h2>'
                '<p class="intro">P0: this week. P1: within 30 days. P2: this quarter. '
                'Every action links to the checks that produced it.</p>'
                '<div class="table-wrap"><table><thead><tr><th>Priority</th><th>Action</th><th>Checks</th><th>Owner</th><th>Effort</th></tr></thead>'
                f'<tbody>{arows}</tbody></table></div></section>')
    toc.append(("plan", "", "What to do, in order", 0))

    shots_html, n_shots = screenshot_section(domain)
    if shots_html:
        body.append('<section class="sec" id="shots" data-title="How the pages render">'
                    '<h2>How the pages render</h2>'
                    '<p class="intro">Captured during the audit with a real browser engine, '
                    'desktop beside mobile, straight from the live site.</p>'
                    f'{shots_html}</section>')
        toc.append(("shots", "", "How the pages render", 0))

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
        sid = "s-" + s["id"].lower()
        n_issue = sum(1 for c in s["checks"] if c["verdict"] == "Issue")
        rows = []
        for c in s["checks"]:
            v = VERDICTS[c["verdict"]]
            sev = (c.get("severity") or "").lower()
            vcell = pill(c["verdict"], "v-" + v) + (" " + pill(c["severity"], "s-" + sev) if c["verdict"] == "Issue" else "")
            ev = evidence_html(c.get("evidence", ""))
            if c["verdict"] == "Needs client data":
                ev = (ev + "<br>" if ev else "") + "<b>Data needed:</b> " + E(c.get("needs", ""))
            fx = ""
            if c["verdict"] == "Issue":
                fx = f"<span class='imp'><b>Impact:</b> {E(c['impact'])}</span>{E(c['fix'])}"
            elif c["verdict"] == "Pass":
                fx = E(c.get("fix") or "No change needed.")
            else:
                fx = E(c.get("fix", ""))
            rows.append(f'<tr data-v="{v}" data-s="{sev}"><td class="id">{E(c["id"])}</td><td class="ck">{E(c["check"])}</td>'
                        f'<td>{vcell}</td><td class="ev">{ev}</td><td class="fx">{fx}</td></tr>')
        extra = agent_matrix(domain) if s["id"] == "AI" else ""
        body.append(f'<section class="sec" id="{sid}" data-title="{E(s["title"])}"><h2><span class="secnum">{E(s["id"])}</span>{E(s["title"])}</h2>'
                    f'<p class="intro">{E(s.get("intro", ""))}</p>'
                    '<div class="table-wrap"><table><thead><tr><th>ID</th><th>Check</th><th>Verdict</th><th>Evidence</th><th>Fix</th></tr></thead>'
                    f'<tbody>{"".join(rows)}</tbody></table></div>{extra}</section>')
        toc.append((sid, s["id"], s["title"], n_issue))

    meth = fd.get("method", {})
    notes = "".join(f"<li>{E(n)}</li>" for n in meth.get("notes", []))
    body.append(f'<section class="sec" id="method" data-title="Scope and method"><h2>Scope and method</h2>'
                f'<p>Domain: <b>{E(fd["domain"])}</b>. Audit date: {E(fd["audit_date"])}. Pages crawled: {E(str(meth.get("pages_crawled", "")))}. '
                f'Checks reported: {len(allc)}.</p><ul>{notes}</ul>'
                '<p>Verdicts: <b>Pass</b> means measured and no change is needed. <b>Issue</b> carries a severity, the evidence, the impact and the exact fix. '
                '<b>Needs client data</b> names the dashboard required. <b>Not tested</b> and <b>Not applicable</b> give the reason.</p></section>')
    toc.append(('method', '', 'Scope and method', 0))
    if fd.get("prompt_set"):
        ps = "".join(f"<li>{E(p)}</li>" for p in fd["prompt_set"])
        body.append(f'<section class="sec" id="prompts" data-title="Prompts to track"><h2>Prompts to track in Wellows</h2><ol>{ps}</ol></section>')
        toc.append(("prompts", "", "Prompts to track", 0))
    if fd.get("sources"):
        src = "".join(f'<li><a href="{E(s["url"])}" target="_blank" rel="noopener">{E(s["title"])}</a></li>' for s in fd["sources"])
        body.append(f'<section class="sec" id="sources" data-title="Sources"><h2>Sources</h2><ul>{src}</ul></section>')
        toc.append(("sources", "", "Sources", 0))

    toc_html = "".join(f'<li><a href="#{i}" data-t="{i}"><span class="n">{E(n)}</span><span>{E(t)}</span>'
                       f'<span class="c">{c if c else ""}</span></a></li>' for i, n, t, c in toc)
    tpl = (KIT_DIR / "templates" / "report.html").read_text(encoding="utf-8")
    client = fd["client_name"]
    out = (tpl.replace("%%TITLE%%", E(f"{client} Technical Audit"))
              .replace("%%DATE%%", E(fd["audit_date"]))
              .replace("%%H1%%", f"Can every search and AI engine reach <em>{E(fd['domain'])}</em>?")
              .replace("%%HEADLINE%%", E(es["headline"]))
              .replace("%%TILES%%", tiles_html).replace("%%TOC%%", toc_html)
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

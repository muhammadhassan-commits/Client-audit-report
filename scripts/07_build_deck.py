"""Build a client PowerPoint deck from findings.json and the collected evidence.

Usage: python3 scripts/07_build_deck.py example.com
Writes: out/<domain>/report/<domain>-technical-audit.pptx
Requires: build_report.py has validated findings.json, and ideally 06_render.py
          has run so there are screenshots to place.

The deck is the same verdicts as the HTML report, cut to what a room can read:
the headline number, the severity split, the top issues one per slide with the
fix, the rendering screenshots, the action plan and the client data requests.
"""
import collections
import re
import sys

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

from common import OUT_ROOT, load_json, normalize_domain

# The Wellows design system, the same tokens templates/report.html uses, so the
# deck and the HTML report read as one document. One brand blue, one typeface,
# and status in emerald, rose and amber rather than green, red and yellow.
FONT = "Parkinsans"

BRAND = RGBColor(0x04, 0x52, 0xF0)          # --brand
DEEP = RGBColor(0x00, 0x47, 0xAB)           # --deep, the one dark background
PALE = RGBColor(0xAB, 0xCE, 0xF6)           # --pale, text on the dark section
SURFACE_BLUE = RGBColor(0xE6, 0xEE, 0xFE)   # --blue-surface
STRONG = RGBColor(0x11, 0x11, 0x11)         # --strong
INK = RGBColor(0x21, 0x25, 0x29)            # --ink
MUTED = RGBColor(0x6C, 0x75, 0x7D)          # --ink-2
LINE = RGBColor(0xE5, 0xE7, 0xEB)           # --line
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PASS = RGBColor(0x06, 0x5F, 0x46)           # --ok, emerald
FAIL = RGBColor(0x88, 0x13, 0x37)           # --bad, rose
WARN = RGBColor(0x78, 0x35, 0x0F)           # --warn, amber
INFO = BRAND

SEV_COLOR = {"Critical": FAIL, "High": RGBColor(0xBE, 0x12, 0x3C),
             "Medium": WARN, "Low": MUTED}
VERDICT_COLOR = {"Pass": PASS, "Issue": FAIL, "Needs client data": INFO,
                 "Not tested": MUTED, "Not applicable": MUTED}

W, H = Inches(13.333), Inches(7.5)          # 16:9
MARGIN = Inches(0.72)
BODY_W = W - 2 * MARGIN


# ------------------------------------------------------------------ utilities

def textbox(slide, left, top, width, height, text, size=18, bold=False,
            color=INK, align=PP_ALIGN.LEFT, spacing=1.15, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text.split("\n") if isinstance(text, str) else list(text)
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        run = p.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        run.font.name = FONT
    return box


def rect(slide, left, top, width, height, fill=None, line=None, radius=False):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        left, top, width, height)
    if radius:
        shape.adjustments[0] = 0.08
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    shape.shadow.inherit = False
    return shape


def slide_base(prs, title=None, eyebrow=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])        # blank
    rect(s, 0, 0, W, H, fill=WHITE)
    rect(s, 0, 0, Inches(0.09), H, fill=BRAND)            # spine
    top = Inches(0.46)
    if eyebrow:
        textbox(s, MARGIN, top, BODY_W, Inches(0.3), eyebrow.upper(), size=11,
                bold=True, color=BRAND)
        top += Inches(0.36)
    if title:
        textbox(s, MARGIN, top, BODY_W, Inches(0.7), title, size=27, bold=True,
                color=STRONG)
        top += Inches(0.82)
    return s, top


def footer(slide, domain, n):
    textbox(slide, MARGIN, H - Inches(0.5), BODY_W, Inches(0.3),
            f"{domain}   ·   Prepared by Wellows   ·   {n}", size=9, color=MUTED)


CPL_14 = 135          # characters per line, 14pt body across BODY_W
CPL_20 = 74           # characters per line, 20pt bold headline


def fit(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# -------------------------------------------------------------------- slides

def title_slide(prs, fd):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, H, fill=DEEP)
    rect(s, 0, 0, W, Inches(0.16), fill=BRAND)
    textbox(s, MARGIN, Inches(2.25), BODY_W, Inches(0.4),
            "TECHNICAL SEO, AEO, GEO AND LLM ACCESSIBILITY AUDIT",
            size=13, bold=True, color=PALE)
    textbox(s, MARGIN, Inches(2.85), BODY_W, Inches(1.5), fd["client_name"],
            size=50, bold=True, color=WHITE)
    textbox(s, MARGIN, Inches(4.25), BODY_W, Inches(0.5), fd["domain"],
            size=21, color=PALE)
    textbox(s, MARGIN, H - Inches(1.25), BODY_W, Inches(0.6),
            f"{fd['audit_date']}   ·   Prepared by {fd.get('prepared_by', 'Wellows')}",
            size=13, color=PALE)
    return s


def summary_slide(prs, fd, counts, sev, n):
    s, top = slide_base(prs, "Executive summary", "The headline")
    es = fd["executive_summary"]
    # The headline is author-written and its length varies, so the block grows
    # with it. A fixed height let a three-line headline run over the tiles.
    head = fit(es["headline"], 420)
    head_rows = max(1, -(-len(head) // CPL_20))
    head_h = Inches(0.37) * head_rows
    textbox(s, MARGIN, top, BODY_W, head_h, head, size=20, bold=True, color=INK)
    top += head_h + Inches(0.3)

    tiles = [("Pass", counts.get("Pass", 0), PASS),
             ("Issues", counts.get("Issue", 0), FAIL),
             ("Needs client data", counts.get("Needs client data", 0), INFO),
             ("Not tested", counts.get("Not tested", 0), MUTED),
             ("Not applicable", counts.get("Not applicable", 0), MUTED)]
    gap = Inches(0.22)
    tw = (BODY_W - gap * (len(tiles) - 1)) / len(tiles)
    for i, (label, value, color) in enumerate(tiles):
        left = MARGIN + i * (tw + gap)
        rect(s, left, top, tw, Inches(1.25), fill=WHITE, line=LINE, radius=True)
        textbox(s, left, top + Inches(0.14), tw, Inches(0.6), str(value), size=33,
                bold=True, color=color, align=PP_ALIGN.CENTER)
        textbox(s, left, top + Inches(0.8), tw, Inches(0.35), label, size=11,
                color=MUTED, align=PP_ALIGN.CENTER)
    top += Inches(1.6)

    issues = counts.get("Issue", 0)
    if issues:
        textbox(s, MARGIN, top, BODY_W, Inches(0.3),
                f"Issues by severity ({issues} of {sum(counts.values())} checks)",
                size=12, bold=True, color=MUTED)
        top += Inches(0.42)
        bar_w = BODY_W
        x = MARGIN
        for name in ("Critical", "High", "Medium", "Low"):
            n_sev = sev.get(name, 0)
            if not n_sev:
                continue
            seg = Emu(int(bar_w * n_sev / issues))
            rect(s, x, top, seg, Inches(0.42), fill=SEV_COLOR[name])
            if seg > Inches(0.95):
                textbox(s, x, top + Inches(0.05), seg, Inches(0.32),
                        f"{name} {n_sev}", size=11, bold=True, color=WHITE,
                        align=PP_ALIGN.CENTER)
            x += seg
    footer(s, fd["domain"], n)
    return s


def narrative_slide(prs, fd, n):
    paras = fd["executive_summary"].get("paragraphs") or []
    if not paras:
        return None
    s, top = slide_base(prs, "What the evidence shows", "Context")
    for para in paras[:4]:
        box = textbox(s, MARGIN, top, BODY_W, Inches(0.9), fit(para, 420),
                      size=15, color=INK, spacing=1.3)
        top += Inches(0.3) + Emu(int(len(fit(para, 420)) / 110 * Inches(0.32)))
        if top > H - Inches(1.1):
            break
    footer(s, fd["domain"], n)
    return s


def issue_slide(prs, fd, check, rank, n):
    s, top = slide_base(prs, fit(check.get("check") or check["id"], 78),
                        f"Priority {rank}  ·  {check['id']}")
    sev = check.get("severity", "Issue")
    pill = rect(s, MARGIN, top, Inches(1.35), Inches(0.36),
                fill=SEV_COLOR.get(sev, FAIL), radius=True)
    tf = pill.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = sev
    run.font.size = Pt(12)
    run.font.bold = True
    run.font.color.rgb = WHITE
    run.font.name = FONT
    top += Inches(0.62)

    # Three fields have to share one slide, and their lengths vary a lot. Budget
    # the remaining height between them before drawing, rather than truncating
    # each to a fixed number of characters and hoping the last one still fits.
    fields = [(label, check.get(key)) for label, key in
              (("Evidence", "evidence"), ("Impact", "impact"), ("Fix", "fix"))]
    fields = [(label, " ".join(str(v).split())) for label, v in fields if v]
    label_h, gap, line_h = Inches(0.3), Inches(0.22), Inches(0.26)
    available = H - Inches(0.72) - top - len(fields) * (label_h + gap)
    lines_left = max(len(fields), int(available / line_h))
    lines_left -= 1 if any(label == "Fix" for label, _ in fields) else 0   # panel padding

    wanted = [max(1, -(-len(v) // CPL_14)) for _, v in fields]
    share = list(wanted)
    while sum(share) > lines_left:
        i = share.index(max(share))
        share[i] -= 1

    for (label, value), rows in zip(fields, share):
        textbox(s, MARGIN, top, BODY_W, Inches(0.26), label.upper(), size=10,
                bold=True, color=BRAND)
        top += label_h
        body = fit(value, rows * CPL_14)
        height = line_h * rows
        if label == "Fix":
            rect(s, MARGIN - Inches(0.14), top - Inches(0.08),
                 BODY_W + Inches(0.28), height + Inches(0.22),
                 fill=SURFACE_BLUE, radius=True)
        textbox(s, MARGIN, top, BODY_W, height, body, size=14, color=INK,
                spacing=1.25)
        top += height + gap
    footer(s, fd["domain"], n)
    return s


def section_table_slide(prs, fd, n):
    s, top = slide_base(prs, "Every area at a glance", "Scorecard")
    rows = []
    for sec in fd["sections"]:
        c = collections.Counter(ch["verdict"] for ch in sec["checks"])
        worst = ""
        sevs = [ch.get("severity") for ch in sec["checks"] if ch["verdict"] == "Issue"]
        for name in ("Critical", "High", "Medium", "Low"):
            if name in sevs:
                worst = name
                break
        rows.append((sec["id"], fit(sec["title"], 42), len(sec["checks"]),
                     c.get("Pass", 0), c.get("Issue", 0), worst))

    half = (len(rows) + 1) // 2
    col_w = (BODY_W - Inches(0.4)) / 2
    for col, chunk in enumerate((rows[:half], rows[half:])):
        x = MARGIN + col * (col_w + Inches(0.4))
        y = top
        headers = ("", "Area", "n", "Pass", "Issue", "")
        widths = [Inches(0.42), col_w - Inches(2.85), Inches(0.4), Inches(0.55),
                  Inches(0.55), Inches(0.93)]
        hx = x
        for head, wd in zip(headers, widths):
            textbox(s, hx, y, wd, Inches(0.25), head, size=9, bold=True,
                    color=MUTED)
            hx += wd
        y += Inches(0.3)
        for sid, title, total, passed, issues, worst in chunk:
            hx = x
            cells = [(sid, INK, True), (title, INK, False), (str(total), MUTED, False),
                     (str(passed), PASS if passed else MUTED, False),
                     (str(issues), FAIL if issues else MUTED, issues > 0),
                     (worst, SEV_COLOR.get(worst, MUTED), False)]
            for (text, color, bold), wd in zip(cells, widths):
                textbox(s, hx, y, wd, Inches(0.26), text, size=10.5, bold=bold,
                        color=color)
                hx += wd
            y += Inches(0.285)
    footer(s, fd["domain"], n)
    return s


def screenshot_slides(prs, fd, domain, n):
    """One slide per key page, desktop beside mobile.

    06_render.py names a shot after a slug of its URL, which is not readable on
    a slide, so the real URL is recovered from render.json by rebuilding the
    same slug. Falling back to the slug would print nonsense like
    "https/demo/example/com", so an unmatched shot shows the domain instead.
    """
    shots = OUT_ROOT / domain / "data" / "shots"
    made = []
    if not shots.is_dir():
        return made
    rendered = (load_json(domain, "render.json") or {}).get("pages", {})
    by_slug = {re.sub(r"[^a-z0-9]+", "-", u.lower())[-60:]: u for u in rendered}
    for shot in sorted(shots.glob("desktop-*.png"))[:5]:
        mobile = shots / shot.name.replace("desktop-", "mobile-", 1)
        slug = shot.stem[len("desktop-"):]
        url = by_slug.get(slug)
        label = url.replace("https://", "").replace("http://", "") if url else domain
        s, top = slide_base(prs, fit(label.rstrip("/") or domain, 70),
                            "How the page renders")
        avail_h = H - top - Inches(0.75)
        if mobile.is_file():
            d_w = BODY_W * 0.68
            _place(s, shot, MARGIN, top, d_w, avail_h, "Desktop 1366x900")
            _place(s, mobile, MARGIN + d_w + Inches(0.3), top,
                   BODY_W - d_w - Inches(0.3), avail_h, "Mobile 390x844")
        else:
            _place(s, shot, MARGIN, top, BODY_W, avail_h, "Desktop 1366x900")
        n += 1
        footer(s, fd["domain"], n)
        made.append(s)
    return made


def _place(slide, image, left, top, max_w, max_h, caption):
    """Place an image inside its box, keeping aspect ratio, with a caption."""
    try:
        with Image.open(image) as im:
            iw, ih = im.size
    except Exception:  # noqa: BLE001
        return
    cap_h = Inches(0.3)
    box_h = max_h - cap_h
    scale = min(max_w / iw, box_h / ih)
    w, h = Emu(int(iw * scale)), Emu(int(ih * scale))
    x = left + (max_w - w) / 2
    rect(slide, x - Inches(0.02), top - Inches(0.02), w + Inches(0.04),
         h + Inches(0.04), fill=None, line=LINE)
    slide.shapes.add_picture(str(image), x, top, width=w, height=h)
    textbox(slide, left, top + h + Inches(0.08), max_w, cap_h, caption, size=10,
            color=MUTED, align=PP_ALIGN.CENTER)


def list_slide(prs, fd, title, eyebrow, items, n, color=INK, numbered=False):
    """A bulleted list over as many slides as it takes.

    Capping at 8 quietly dropped 6 of the 14 strengths and 6 of the 13 client
    data requests, which is the half of the list the client has to act on.
    """
    if not items:
        return n - 1
    # Round up on the measured characters per line. Dividing and adding one gave
    # a spare line whenever the text filled its last line, which showed up as
    # uneven gaps between bullets.
    laid = [(it, max(1, -(-len(fit(it, 300)) // (CPL_14 - 8)))) for it in items]
    budget = H - Inches(0.9) - Inches(1.3)
    heights = [Inches(0.28) * rows + Inches(0.22) for _, rows in laid]
    def pack_to_brim():
        pages, page, used = [], [], 0
        for item, height in zip(laid, heights):
            if page and used + height > budget:
                pages.append(page)
                page, used = [], 0
            page.append(item)
            used += height
        if page:
            pages.append(page)
        return pages

    # Pack to the brim once to learn how many slides this really needs, then
    # spread the bullets evenly over that many, so the last slide does not hold
    # one bullet on its own.
    n_pages = len(pack_to_brim())
    pages, i = [], 0
    for left in range(n_pages, 0, -1):
        want = -(-(len(laid) - i) // left)          # even share of what is left
        page, used = [], 0
        while len(page) < want and i < len(laid) and used + heights[i] <= budget:
            page.append(laid[i])
            used += heights[i]
            i += 1
        pages.append(page)
    while i < len(laid):                             # anything the share missed
        pages[-1].append(laid[i])
        i += 1

    i = 0
    for pg, page in enumerate(pages, 1):
        part = "" if len(pages) == 1 else f"  ·  {pg} of {len(pages)}"
        s, top = slide_base(prs, title, f"{eyebrow}{part}")
        for item, rows in page:
            i += 1
            bullet = f"{i}." if numbered else "•"
            textbox(s, MARGIN, top, Inches(0.52), Inches(0.3), bullet, size=14,
                    bold=True, color=BRAND)
            textbox(s, MARGIN + Inches(0.52), top, BODY_W - Inches(0.52),
                    Inches(0.28) * rows, fit(item, 300), size=14, color=color,
                    spacing=1.25)
            top += Inches(0.28) * rows + Inches(0.22)
        footer(s, fd["domain"], n)
        n += 1
    return n - 1


def actions_slide(prs, fd, n):
    """The whole action plan, over as many slides as it takes.

    A single slide held 7 of 25 actions and said nothing about the other 18,
    which read as the plan rather than the first page of it.
    """
    actions = fd.get("actions") or []
    if not actions:
        return n
    widths = [Inches(0.95), BODY_W - Inches(3.6), Inches(1.5), Inches(1.15)]
    pages = []
    page, used = [], Inches(0)
    budget = H - Inches(0.9) - Inches(1.3) - Inches(0.34)      # below the header row
    for act in actions:
        body = fit(act.get("action", ""), 150)
        checks = " ".join(str(act.get("checks", "")).split())
        # The Checks column is narrower than the Action column, and a row with
        # 7 check IDs needs two lines rather than an ellipsis.
        rows = max(-(-len(body) // 95), -(-len(checks) // 22), 1)   # measured, 11pt
        height = Inches(0.26) * rows + Inches(0.16)
        if used + height > budget and page:
            pages.append(page)
            page, used = [], Inches(0)
        page.append((act, body, rows))
        used += height
    if page:
        pages.append(page)

    for i, page in enumerate(pages, 1):
        part = "" if len(pages) == 1 else f"  ·  {i} of {len(pages)}"
        s, top = slide_base(prs, "Action plan", f"What to do, in order{part}")
        hx = MARGIN
        for head, wd in zip(("Priority", "Action", "Checks", "Owner"), widths):
            textbox(s, hx, top, wd, Inches(0.26), head.upper(), size=9.5,
                    bold=True, color=MUTED)
            hx += wd
        top += Inches(0.34)
        for act, body, rows in page:
            hx = MARGIN
            height = Inches(0.26) * rows
            cells = [(act.get("priority", ""), BRAND, True),
                     (body, INK, False),
                     (fit(checks, 48), MUTED, False),
                     (fit(act.get("owner", ""), 16), MUTED, False)]
            for (text, color, bold), wd in zip(cells, widths):
                textbox(s, hx, top, wd, height, text, size=11, bold=bold,
                        color=color)
                hx += wd
            top += height + Inches(0.16)
        footer(s, fd["domain"], n)
        n += 1
    return n - 1


def closing_slide(prs, fd):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, H, fill=DEEP)
    rect(s, 0, H - Inches(0.16), W, Inches(0.16), fill=BRAND)
    textbox(s, MARGIN, Inches(2.9), BODY_W, Inches(0.9),
            "Every verdict in this deck is evidenced.", size=30, bold=True,
            color=WHITE)
    textbox(s, MARGIN, Inches(3.9), BODY_W, Inches(0.9),
            "The full report lists all 133 checks with the measured value, the "
            "impact and the exact fix.", size=16,
            color=PALE)
    textbox(s, MARGIN, H - Inches(1.2), BODY_W, Inches(0.5),
            f"Prepared by {fd.get('prepared_by', 'Wellows')}   ·   {fd['audit_date']}",
            size=13, color=PALE)
    return s


# ----------------------------------------------------------------------- main

def build(domain):
    fd = load_json(domain, "../findings.json")
    if not fd:
        sys.exit(f"out/{domain}/findings.json not found. Write it first, then "
                 f"run build_report.py, then this.")

    all_checks = [c for sec in fd["sections"] for c in sec["checks"]]
    counts = collections.Counter(c["verdict"] for c in all_checks)
    sev = collections.Counter(c.get("severity") for c in all_checks
                              if c["verdict"] == "Issue")

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    title_slide(prs, fd)
    n = 1
    summary_slide(prs, fd, counts, sev, n := n + 1)
    narrative_slide(prs, fd, n := n + 1)
    section_table_slide(prs, fd, n := n + 1)

    by_id = {c["id"]: c for c in all_checks}
    top_issues = [by_id[t["id"]] for t in fd["executive_summary"].get("top_issues", [])
                  if t["id"] in by_id]
    if not top_issues:
        order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        top_issues = sorted([c for c in all_checks if c["verdict"] == "Issue"],
                            key=lambda c: order.get(c.get("severity"), 9))[:5]
    for rank, check in enumerate(top_issues[:6], 1):
        issue_slide(prs, fd, check, rank, n := n + 1)

    for _ in screenshot_slides(prs, fd, domain, n):
        n += 1

    n = list_slide(prs, fd, "What is already working", "Strengths",
               fd.get("working_well") or [], n := n + 1, color=INK)
    n = actions_slide(prs, fd, n + 1)
    needs = [f"{c['id']}: {c.get('needs') or c.get('evidence', '')}"
             for c in all_checks if c["verdict"] == "Needs client data"]
    n = list_slide(prs, fd, "What we need from you", "Client data requests", needs,
               n := n + 1, numbered=True)
    closing_slide(prs, fd)

    rd = OUT_ROOT / domain / "report"
    rd.mkdir(parents=True, exist_ok=True)
    path = rd / f"{domain}-technical-audit.pptx"
    prs.save(str(path))
    print(f"OK deck -> {path} ({len(prs.slides)} slides)")
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: 07_build_deck.py <domain>")
    build(normalize_domain(sys.argv[1]))

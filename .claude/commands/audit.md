---
description: Run the full Wellows technical SEO, AEO, GEO and LLM accessibility audit for a domain and build the client report
argument-hint: <domain> [client name]
---

Run the complete Wellows site audit for: **$ARGUMENTS**

The first word is the domain. Any remaining words are the client's display name; if none is given, derive it from the site's Organization schema or title.

Follow `CLAUDE.md` in this folder exactly:

1. **Setup:** if `python3 -c "import requests, bs4, lxml"` fails, run `python3 -m pip install -r requirements.txt`. Try to install Playwright and Chromium for the rendering checks. If that fails, continue and mark the M checks Not tested with the reason.
2. **Collect evidence:** run `python3 scripts/run_all.py <domain>`. If preflight says the site is unreachable, or Chrome gets a challenge page, stop and tell me.
3. **Read and check:**
   - Read all evidence in `out/<domain>/data/`.
   - Do the manual checks the catalogue lists.
   - Use web search for entity profiles if available.
   - Never exceed 2 requests per second.
4. **Write findings:** write `out/<domain>/findings.json` covering every check ID in `framework/checks.md`, following `framework/findings-schema.md`. Every verdict is evidenced, and every passing check says "No change needed."
5. **Build:** run `python3 scripts/build_report.py <domain>` and iterate until it builds with no errors or warnings.
6. **Reply** with:
   - the report path
   - the verdict counts
   - the top 5 issues with their fixes
   - the list of client data requests (every Needs client data item)
   - anything not tested, and why

Work autonomously until the report is built. Ask only if authorization is unclear or the site is unreachable.

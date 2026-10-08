# findings.json format

Claude writes `out/<domain>/findings.json` after reading the evidence. Then it
runs `python3 scripts/build_report.py <domain>`. The builder validates the file
and refuses to build until every error is fixed.

```json
{
  "domain": "example.com",
  "client_name": "Example Inc.",
  "audit_date": "2026-10-06",
  "prepared_by": "Wellows",
  "executive_summary": {
    "headline": "One sentence verdict with the single most important number.",
    "paragraphs": ["2 to 4 short paragraphs. Plain, specific, no hedging."],
    "top_issues": [
      {"id": "AI5", "title": "Cloudflare challenges GPTBot and ClaudeBot on every key URL", "fix": "Add a WAF Skip rule for verified AI crawler IP ranges."}
    ]
  },
  "method": {
    "pages_crawled": 150,
    "notes": [
      "Evidence collected on 6 Oct 2026 from a single network location at 2 requests per second.",
      "Crawler tests used each vendor's published user agent from our network, not from the crawler's own IP ranges. They prove robots.txt rules and how the server or CDN treats that user agent. How the CDN treats the real crawler IPs is listed under Needs client data."
    ]
  },
  "sections": [
    {
      "id": "AI",
      "title": "LLM and search crawler access",
      "intro": "One or two sentences: what this area decides and the result.",
      "checks": [
        {"id": "AI1", "check": "robots.txt reachable and parseable", "verdict": "Pass",
         "evidence": "200 text/plain, 1.2 KB, 0 parse warnings (robots.txt).", "fix": "No change needed."},
        {"id": "AI5", "check": "Crawler UAs get a 200 and full HTML", "verdict": "Issue", "severity": "Critical",
         "evidence": "GPTBot and ClaudeBot received HTTP 403 with cf-mitigated: challenge on all 6 key URLs. Chrome received 200.",
         "impact": "ChatGPT and Claude cannot read or cite these pages.",
         "fix": "In Cloudflare > Security > WAF, add a custom rule: (cf.verified_bot_category in {\"AI Crawler\" \"Search Engine Crawler\"}) with action Skip for Bot Fight Mode and managed challenges."},
        {"id": "AI11", "check": "Real-IP treatment of crawlers at the edge", "verdict": "Needs client data",
         "needs": "Cloudflare > Security > Events, last 28 days, filtered by verified bot category, grouped by action.",
         "evidence": "Cannot be observed from outside the client's network."},
        {"id": "A11", "check": "hreflang", "verdict": "Not applicable", "evidence": "Single-language site: no hreflang and no localized URLs in the sitemaps."}
      ]
    }
  ],
  "working_well": ["Short, specific statements of what passes, each with its number."],
  "actions": [
    {"priority": "P0", "action": "Allow verified AI crawlers through the WAF", "checks": "AI5, AI11", "owner": "DevOps", "effort": "2 hours"}
  ],
  "prompt_set": ["best social media scheduling tool for agencies"],
  "sources": [{"title": "Google: robots.txt specification", "url": "https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt"}]
}
```

## Rules the builder enforces

- `verdict` is one of: `Pass`, `Issue`, `Needs client data`, `Not tested`, `Not applicable`.
- **Pass:** `evidence` is required. `fix` defaults to "No change needed."
- **Issue:**
  - `severity` is required: `Critical`, `High`, `Medium` or `Low`.
  - `evidence`, `impact` and `fix` are all required.
- **Needs client data:** `needs` is required. Name the exact dashboard or export and what to look for.
- **Not tested** and **Not applicable:** `evidence` holds the reason.
- **No em dashes** (U+2014) in any string. The builder fails on them.
- **Hedging words** in Pass and Issue text produce a warning to rewrite: may, might, possibly, could potentially, consider, perhaps, it seems.
- **Every check ID** in `framework/checks.md` must appear exactly once. Missing IDs fail the build.
- **Extra checks** you add get IDs with an `X` prefix (X1, X2, ...) in the most relevant section. Mention them in the method notes.
- The crawler access matrix, engine dependency table and verdict counts are generated from the data files. Do not retype them.

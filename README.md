# Wellows Site Audit Kit

Pass a domain and get a client-ready **Technical SEO, AEO, GEO and LLM accessibility** report. The report is Wellows-branded, has a reading-progress bar, filters and light/dark mode, and gives every check an evidenced verdict.

## Setup (once)

1. Unzip anywhere, e.g. `~/audits/wellows-site-audit/`.
2. Install Python 3.10+ and Claude Code (terminal, desktop Code tab, or IDE).
3. Optional, for speed data: get a free PageSpeed Insights API key (Google Cloud console > APIs > PageSpeed Insights API > Credentials). Then:
   ```
   export PSI_API_KEY=your_key          # macOS / Linux
   setx PSI_API_KEY your_key            # Windows
   ```
4. Open Claude Code **in this folder**, so it reads `CLAUDE.md` and the `/audit` command:
   ```
   cd ~/audits/wellows-site-audit
   claude
   ```

## Run an audit

In Claude Code:
```
/audit socialchamp.com Social Champ
```

In any Claude setup without slash commands, paste:
```
Run the Wellows site audit for socialchamp.com (client name: Social Champ). Follow CLAUDE.md in this folder exactly, end to end, until the report is built.
```

Claude installs the dependencies, collects the evidence, writes the findings and builds the report. Output:
```
out/socialchamp.com/report/socialchamp.com-technical-audit.html   <- send this to the client
out/socialchamp.com/report/summary.md
out/socialchamp.com/findings.json                                  <- every verdict
out/socialchamp.com/data/                                          <- raw evidence
```

## Run the scripts yourself (optional)

```
python3 -m pip install -r requirements.txt
python3 scripts/run_all.py example.com --max-pages 150
# write out/example.com/findings.json (see framework/findings-schema.md)
python3 scripts/build_report.py example.com
```

## What it checks

133 checks in 18 areas, listed in `framework/checks.md`:
- LLM and search crawler access for 28 agents (robots.txt, HTTP status, challenge pages, opt-outs, llms.txt)
- Crawlability, URLs, canonicals, meta, headings, content, media and links
- Structured data and entity, and social tags
- Core Web Vitals and Lighthouse
- Security and exposed paths
- Rendering parity and content parsing
- AEO, GEO, and monitoring and operations

## Run it as a service (Render)

`webapp/main.py` wraps the collectors in a small HTTP API so audits can be started and
collected remotely. An audit runs far longer than any request timeout, so each run happens
in a background thread and the caller polls.

**What the service does and does not do.** It collects evidence and builds the report from a
findings file. It does **not** write `findings.json`: that is a judgement step made against the
evidence. Upload the file and the service validates and builds, or returns the validation errors.

```
POST /audits                      {"domain": "example.com"}  -> job id
GET  /audits/<id>                 status, log tail, evidence file list
GET  /audits/<id>/files/<path>    any file under out/<domain>/
POST /audits/<id>/findings        upload findings.json, builds or returns errors
GET  /audits/<id>/report          the built client report
GET  /healthz                     unauthenticated, for the health check
```

People sign in at `/` with an email and password from `AUDIT_USERS`, which returns a
session signed with HMAC-SHA256 and good for 7 days. Every route except `/healthz` and
`/login` needs that session as `Authorization: Bearer <session>`, or the optional
`AUDIT_API_TOKEN` for scripted callers. Changing a password invalidates every session
signed under the old one.

**Deploy.** Point Render at this repo with Blueprints > New (it reads `render.yaml`), then set:

| Variable | Required | Value |
|---|---|---|
| `AUDIT_USERS` | Yes | Sign-in accounts as `email:password`, comma separated. A password may contain `:` but not `,`. The service returns 503 with no accounts and no token. |
| `AUDIT_API_TOKEN` | No | A token for scripts and CI that cannot use the sign-in form. |
| `AUDIT_ALLOWED_DOMAINS` | Yes | Comma-separated hosts you may audit. A host matches itself and its subdomains. The service refuses every audit without it, so it cannot be used as an open crawler. |
| `PSI_API_KEY` | No | PageSpeed Insights key. Without it the K checks can rate-limit. |
| `AUDIT_OUT_DIR` | Set by the blueprint | `/data/out`, on the mounted disk. |
| `AUDIT_MAX_CONCURRENT` | No | Parallel audits, default 1. |

**Two things to know before you deploy.** Everyone signed in sees every report on the
instance: there is no per-account separation. And `render.yaml` asks
for a 1 GB disk, which needs a paid plan: on the free plan evidence and reports are lost
whenever the instance restarts.

Run it locally the same way:

```
python3 -m pip install -r requirements.txt -r requirements-web.txt
AUDIT_USERS=you@wellows.com:devpassword AUDIT_ALLOWED_DOMAINS=example.com uvicorn webapp.main:app --reload
```

## Limits to know

- **Network:** crawler tests use each vendor's user agent from your network, not from the crawler's IPs. How the CDN treats the real crawlers needs the client's CDN logs; the report lists this as a data request.
- **Request rate:** 2 requests per second, about 150 pages by default. Exposed-path checks are one GET each. No logins, forms or exploitation.
- **Client data:** Search Console, Bing Webmaster Tools, CDN and analytics data must come from the client. Each item names the exact dashboard.
- **Permission:** run it only on domains you own or are engaged to audit.

## Updating

- Crawler user agents: `framework/agents.json`
- Checks and benchmarks: `framework/checks.md` (the builder requires every ID to be reported)
- Branding: `templates/report.html`

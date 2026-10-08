# Wellows Technical SEO, AEO, GEO and LLM Accessibility Audit: Check Catalogue

Every audit reports **every check below** in `findings.json`, using its ID. The
section order here is the section order of the report.

**Columns**
- **Severity if failed** is the default. Raise or lower it only with a reason written in the finding.
- **Evidence** names the file under `out/<domain>/data/` (and its field) that proves the result. It can also be a manual method.

**Severity scale**

| Severity | Meaning |
|---|---|
| Critical | Blocks crawling, indexing or AI access for key pages or whole engines |
| High | A measurable loss of visibility, or a broken experience |
| Medium | Best practice missed, with a clear SEO, AEO or GEO cost |
| Low | Polish |

**Verdicts**

| Verdict | Use when |
|---|---|
| Pass | Measured and meets the benchmark. No change needed. |
| Issue | Measured and fails the benchmark. |
| Needs client data | Can only be measured from the client's dashboards, logs or accounts. |
| Not tested | Could not be measured in this run. Give the reason. |
| Not applicable | Does not apply to this site, e.g. hreflang on a single-language site. Give the reason. |

---

## AI. LLM and search crawler access

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| AI1 | robots.txt reachable and parseable | 200, `text/plain`, under 500 KB, no parse warnings, not challenged | Critical | preflight.robots |
| AI2 | Search crawlers allowed by robots.txt | Googlebot, Bingbot and Applebot allowed on all key URLs | Critical | crawler_access.agents[].robots |
| AI3 | AI search and user-fetch agents allowed | OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User, PerplexityBot, Perplexity-User, Meta-ExternalFetcher, DuckAssistBot, MistralAI-User allowed on all key URLs | Critical | crawler_access.agents[].robots |
| AI4 | AI training agents match a stated policy | GPTBot, ClaudeBot, Google-Extended, Applebot-Extended, Meta-ExternalAgent, CCBot, Bytespider, cohere-ai: allowed or blocked deliberately. Report the current state and the business trade-off. | Medium | crawler_access.agents[].robots |
| AI5 | Crawler UAs get a 200 and full HTML | Every agent with a UA: status 200 on all key URLs, no challenge, size at least 0.8 of the Chrome baseline | Critical | crawler_access.agents[].fetch |
| AI6 | Link-preview bots served | facebookexternalhit, Twitterbot and LinkedInBot get a 200 with OG tags | Medium | crawler_access.agents[].fetch |
| AI7 | No AI opt-out signals on content to be cited | No `noai`, `noimageai`, `nosnippet` or `max-snippet:0` in X-Robots-Tag or meta. `data-nosnippet` only on boilerplate. | High | crawler_access.agents[].fetch, crawl.jsonl |
| AI8 | CDN-managed robots or AI blocking | No unintended CDN-injected AI Disallow groups or Content-Signal lines | High | preflight.robots.other_directives / cloudflare_managed_signature |
| AI9 | llms.txt | Present, valid markdown, sampled links return 200, describes core pages. Optional: absence is Low. | Low | preflight.special_files./llms.txt |
| AI10 | llms-full.txt usable | If present: under 10 MB, current, links valid. Over 10 MB is an Issue, since many fetchers truncate. | Low | preflight.special_files./llms-full.txt |
| AI11 | Real-IP treatment of crawlers at the edge | CDN or WAF security events show no Block or Challenge on verified bot IPs in the last 28 days | Critical | Needs client data: CDN security events filtered by verified bots |
| AI12 | Verified-bot allow rules | WAF Skip rules for verified crawler IP ranges (Bingbot, Googlebot, OpenAI, Perplexity, Apple) | High | Needs client data: WAF rules export |
| AI13 | Bot visit recency per agent | Each allowed agent seen within 7 days in server or CDN logs | Medium | Needs client data: logs or a bot analytics tool |
| AI14 | Answer test across engines | ChatGPT, Perplexity, Gemini, Copilot, Claude, Grok and DeepSeek describe the brand correctly when asked a fixed prompt set | Medium | Manual. List the prompts in the finding. Mark Not tested if not run. |
| AI15 | Subdomain crawl controls | App, login and staging subdomains are noindex or blocked. Public subdomains (help, docs, blog) are crawlable and canonical. | High | crawler_access.subdomains |
| AI16 | UA strings current | The agents.json strings match vendor docs as of the audit date | Low | Manual: vendor docs |

## A. Crawlability and indexation

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| A1 | Protocol and host canonicalisation | http and https, www and non-www all reach the preferred origin in one 301 hop | High | preflight.host_variants |
| A2 | robots.txt variants | The http robots.txt 301s to the https one | Low | preflight.robots.variants |
| A3 | XML sitemap present and declared | Reachable, valid XML, listed in robots.txt | High | preflight.sitemap_candidates, sitemaps.json |
| A4 | Sitemap health | Sampled sitemap URLs: 0 non-200, 0 redirects, 0 noindex. lastmod on 90% or more. | High | crawl_summary.non200_sitemap_urls, redirected_sitemap_urls, sitemaps.lastmod_coverage |
| A5 | Each URL in one sitemap; no off-host URLs | 0 duplicates across sitemaps, 0 off-host | Low | sitemaps.in_multiple_sitemaps, off_host_count |
| A6 | No unintended noindex | 0 money or content pages noindexed | Critical | crawl_summary.checks.noindex_pages |
| A7 | Soft 404 | A made-up URL returns 404 or 410 with a helpful page | Medium | preflight.soft404 |
| A8 | Redirect chains | Internal links and sitemap URLs at most 1 hop, 0 loops | Medium | links.json, crawl_summary |
| A9 | URL normalisation | Trailing slash, case, http and index.html variants 301 to the canonical in one hop, or return 404 | Medium | server.url_normalisation |
| A10 | Parameter, search and faceted URLs controlled | No indexable `?s=`, sort or filter URLs in sitemaps or crawl | Medium | crawl_summary.checks.url_params |
| A11 | hreflang (multi-language only) | Valid codes, self-reference, return tags, one x-default | High | crawl.jsonl hreflang |
| A12 | Index coverage | Search Console indexed count within about 10% of sitemap URLs; no growth in "Crawled, not indexed" | Medium | Needs client data: Search Console Pages report |
| A13 | Bing index parity | Bing Webmaster Tools indexed count within 20% of Google's | Medium | Needs client data: Bing Webmaster Tools |
| A14 | IndexNow | Key file present and pings sent on publish | Low | Manual: plugin or CDN setting; key file if discoverable |
| A15 | Crawl stats and server errors | Search Console crawl stats: over 99% 200, no 5xx spikes, average response under 500 ms | Medium | Needs client data: Search Console Crawl stats |

## B. URL structure

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| B1 | URL length | 75 characters or fewer | Low | crawl_summary.checks.url_over_75_chars |
| B2 | Readable URLs | Lowercase, hyphens, no underscores, no non-ASCII | Low | crawl_summary.checks.url_uppercase_or_underscore |
| B3 | No parameters on canonical URLs | 0 | Medium | crawl_summary.checks.url_params |

## C. Canonicalisation

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| C1 | Canonical present, exactly one | 100% of pages | High | missing_canonical, multiple_canonical |
| C2 | Canonical self-referencing or intentional | Mismatches are only deliberate consolidations | High | canonical_not_self |
| C3 | Canonical target healthy | Target is 200, not a redirect, not noindex | High | links.json, crawl.jsonl |
| C4 | Header and HTML canonicals agree | A `Link` header canonical, if present, equals the HTML canonical | Medium | crawl.jsonl canonical_header |

## D. Meta and head

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| D1 | Title present and unique | 100% present, 0 duplicates | High | missing_title, duplicate_titles |
| D2 | Title length | 30 to 60 characters | Low | title_len_out_of_range_30_60 |
| D3 | Meta description present and unique | 100% present, 0 duplicates | Medium | missing_description, duplicate_descriptions |
| D4 | Description length | 120 to 160 characters | Low | description_len_out_of_range_120_160 |
| D5 | Charset first, one viewport, lang attribute | All pages | Medium | charset_not_first, viewport_not_one, missing_lang |
| D6 | No meta tags in body | 0 | Medium | meta_in_body |

## E. Headings

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| E1 | Exactly one H1 | All pages | Medium | h1_not_exactly_one |
| E2 | Logical hierarchy | No skipped levels | Low | heading_level_skips |
| E3 | No empty headings | 0 | Low | empty_headings |

## F. Content quality

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| F1 | Word count by page type | 250 words or more on standard pages; 1,000 or more on guides | Medium | thin_under_250_words |
| F2 | No placeholder text | 0 lorem ipsum, TODO or dummy text | High | lorem_or_todo |
| F3 | Internal duplicate content | No near-duplicate or geo-cloned pages | High | Manual: compare titles, H1s and word counts of suspect clusters in crawl.jsonl |
| F4 | Readability | Flesch Reading Ease 50 to 70 on key pages | Low | Manual or a readability library; Not tested if not computed |
| F5 | Evidence and citations | Claims with numbers cite a source | Low | Manual review of the top 5 pages |

## G. Media

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| G1 | Alt text | 100% of content images have alt; decorative images use `alt=""` | Medium | images_missing_alt |
| G2 | Modern formats | WebP or AVIF for 80% or more of content images | Low | images_legacy_format, performance.lab.modern-image-formats |
| G3 | Dimensions declared | width and height on 90% or more of images | Low | images_without_dimensions |
| G4 | LCP image not lazy-loaded; below-fold images lazy | Per Lighthouse | Medium | performance.lab |
| G5 | Video SEO (if video) | VideoObject schema, transcript, thumbnail | Low | crawl.jsonl jsonld_types |

## H. Links

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| H1 | Broken internal links | 0 | High | links.internal_broken |
| H2 | Broken external links | 0 | Low | links.external_broken |
| H3 | Internal links point to final URLs | 0 links to redirects | Low | links.internal_redirecting |
| H4 | HTTPS links only | 0 http links | Medium | http_links |
| H5 | Anchor text quality | Generic anchors ("click here", "read more") under 5% of links | Low | generic_anchors |
| H6 | No internal nofollow | 0 | Low | internal_nofollow |
| H7 | Links per page | 100 or fewer | Low | over_100_links |
| H8 | Orphan and deep pages | Key pages within 3 clicks of the homepage | Medium | Manual: crawl depth from a full crawler, or Not tested |

## I. Structured data and entity

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| I1 | JSON-LD present on key templates | Every key template has relevant JSON-LD | Medium | no_jsonld, jsonld_types_seen |
| I2 | Zero parse errors | 0 | High | jsonld_parse_errors |
| I3 | Organization and WebSite on the homepage | Organization has name, url, logo, sameAs and contactPoint | Medium | crawl.jsonl (home) |
| I4 | Product or SoftwareApplication offers on pricing | Offers match visible prices | Medium | crawl.jsonl (pricing) plus a visible-price comparison |
| I5 | Article schema with author Person and dates | On blog posts | Medium | crawl.jsonl (blog) |
| I6 | BreadcrumbList on hierarchical pages | Present | Low | jsonld_types_seen |
| I7 | Entity graph via @id | Nodes reference each other with stable @id | Low | crawl.jsonl jsonld_ids |
| I8 | sameAs coverage | LinkedIn, X, YouTube, Crunchbase, G2 or Capterra, Wikidata (where they exist) | Medium | sameas_seen plus a web search |
| I9 | Schema matches visible content | No marked-up facts absent from the page | High | Manual spot-check of 3 pages |
| I10 | Schema in raw HTML | JSON-LD is server-rendered | Medium | render.json parity.jsonld_raw_vs_rendered |

## J. Social tags

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| J1 | Open Graph complete | og:title, og:description, og:image, og:url and og:type on all pages | Medium | og_incomplete |
| J2 | Twitter card | twitter:card present | Low | twitter_card_missing |
| J3 | Social image valid | 1200x630 or larger, HTTPS, loads | Low | Fetch og:image for 3 pages |

## K. Performance and Core Web Vitals

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| K1 | LCP (field, p75, mobile) | 2.5 s or less | High | performance.field_url / field_origin |
| K2 | INP (field, p75) | 200 ms or less | High | performance |
| K3 | CLS (field, p75) | 0.1 or less | High | performance |
| K4 | TTFB | Field p75 under 800 ms; crawl median under 600 ms | Medium | performance, crawl_summary.ttfb_ms_median |
| K5 | Lighthouse performance score (mobile) | 90 or above is good; 50 to 89 is an Issue (Medium); under 50 is an Issue (High) | Medium | performance.scores |
| K6 | Render-blocking resources | None flagged | Medium | performance.lab.render-blocking-resources |
| K7 | Unused JS and CSS | Under 10% of bytes, per Lighthouse savings | Low | performance.lab |
| K8 | Text compression | Brotli or gzip on HTML, CSS and JS | Medium | server.compression, static_assets |
| K9 | Caching | Static assets cached 7 days or more; ETag or Last-Modified on HTML with 304 support | Low | server.static_assets, conditional_home |
| K10 | HTML size | Under 100 KB uncompressed on key pages | Low | html_over_100kb |
| K11 | CDN delivery and HTTP/2 or HTTP/3 | Assets via CDN; HTTP/2 at least; HTTP/3 advertised | Low | server.http_versions, alt_svc |
| K12 | Third-party script cost | Under 1 s total main-thread time | Medium | performance.lab.third-party-summary |

## L. Security and delivery

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| L1 | Valid TLS certificate | Valid chain, more than 30 days to expiry | Critical | server.tls |
| L2 | Modern TLS only | TLS 1.2 and 1.3 accepted; 1.0 and 1.1 refused | Medium | server.tls.protocol_support |
| L3 | HSTS | Present with max-age of 1 year or more | Medium | server.security_headers |
| L4 | Security headers | CSP, X-Content-Type-Options, frame-ancestors or X-Frame-Options, Referrer-Policy | Low | server.missing_security_headers |
| L5 | No mixed content | 0 | High | mixed_content |
| L6 | No exposed sensitive paths | 0 exposures among /.git, /.env, WordPress users API, phpinfo, server-status, .DS_Store | Critical | server.exposed_true |
| L7 | Safe Browsing | Clean | Critical | Manual: transparencyreport.google.com safe browsing lookup |
| L8 | No rate-limit blocks at polite speed | 10 requests at 2 per second all return 200 | Medium | server.burst_10_at_2rps |

## M. Code health and rendering

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| M1 | Rendered vs raw parity | Title, canonical and H1 identical; raw HTML holds 80% or more of rendered words and links | Critical | render.pages[].parity |
| M2 | Mobile vs desktop parity | Same H1, words and links within 10%, same schema | High | render.pages[].mobile_parity |
| M3 | Console errors | 0 blocking JS errors on load | Low | render.pages[].*.console_errors |
| M4 | Interstitials and cookie banners | Largest overlay covers 30% or less of the mobile viewport | Medium | render.pages[].mobile.largest_overlay |
| M5 | DOM integrity | 0 duplicate IDs on key pages | Low | duplicate_ids |
| M6 | No deprecated tags | 0 | Low | deprecated_tags |
| M7 | Lighthouse SEO and accessibility | SEO score 95 or above; accessibility 90 or above; list failed audits | Medium | performance.scores, failed_seo_audits, failed_a11y_audits |

## P. Content parsing for machines

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| P1 | Semantic landmarks | `<main>` on all templates; nav, header and footer marked | Medium | no_main_landmark |
| P2 | Main content share | `<main>` holds 60% or more of page words on content pages | Low | crawl.jsonl main_word_share |
| P3 | Heading anchor IDs | 50% or more of H2 and H3 have ids, so engines can deep-link | Low | h23_without_anchor_ids |
| P4 | Real tables and lists | Comparison and pricing data in `<table>`, steps in `<ol>` | Medium | pages_with_tables plus a manual look at the pricing and comparison pages |
| P5 | Text-to-HTML ratio | 10% or more on content pages | Low | crawl.jsonl text_html_ratio |
| P6 | Media text equivalents | Videos have transcripts; charts and infographics have HTML summaries | Low | Manual |

## Q. AEO (answer engines)

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| Q1 | Question-led headings | Key pages and top posts use real query phrasing in H2 and H3 | Medium | question_headings_total plus a manual read |
| Q2 | Answer-first paragraphs | First paragraph under an H2 answers in 40 to 60 words | Medium | h2_first_para_words_median_overall |
| Q3 | FAQ blocks | Product, pricing and pillar pages carry 4 to 8 real questions with matching schema | Medium | pages_with_faq_signals, FAQPage in jsonld_types_seen |
| Q4 | Definitions | Core terms defined near the top of pillar pages | Low | Manual |
| Q5 | Snippet controls | No nosnippet or max-snippet limits on content we want quoted | High | AI7 evidence |
| Q6 | Business profiles | Google Business Profile, Bing Places and Apple Business Connect claimed and consistent | Low | Needs client data |

## R. GEO (generative engines)

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| R1 | Self-contained passages | Sections name their subject and stand alone | Medium | Manual review of 3 key pages |
| R2 | Original data | Proprietary statistics or studies, with the method stated | Medium | Manual |
| R3 | Visible freshness | "Last updated" dates on key pages and posts; dateModified in schema | Medium | pages_with_visible_dates |
| R4 | Author E-E-A-T | Named authors with bio pages and Person schema | Medium | pages_with_author |
| R5 | Trust pages | About, Contact, Privacy, Terms linked in the footer | Medium | preflight.key_urls plus home links |
| R6 | Comparison and alternatives content | "X vs Y" and "alternatives" pages exist, current, in HTML tables | Medium | Sitemap URL patterns (vs, alternative, compare) |
| R7 | Third-party entity profiles | Wikidata, Crunchbase, G2, Capterra, LinkedIn exist and match the site facts | Medium | Web search, or Not tested |
| R8 | Brand mention footprint | Present on the sources AI engines cite for the category (Reddit, YouTube, review sites, listicles) | Medium | Needs client data: Wellows citation tracking |
| R9 | Prompt set for tracking | 15 or more category prompts defined for monitoring in Wellows | Low | Deliverable: list them in the finding |

## N. Monitoring and operations

| ID | Check | Pass when | Severity if failed | Evidence |
|---|---|---|---|---|
| N1 | Analytics installed once | One GA4 (or equivalent) tag | Medium | Search home.html for gtag or GTM IDs |
| N2 | Search Console and Bing Webmaster verified | Both verified | High | Needs client data. A verification meta tag in home.html is supporting evidence. |
| N3 | Per-bot alerting | Alerts on zero visits or edge blocks for allowed crawlers | Medium | Needs client data |
| N4 | Log retention | 90 days or more | Low | Needs client data |
| N5 | Maintenance responses | Maintenance mode returns 503 with Retry-After | Low | Needs client data |
| N6 | Staging protection | Publicly linked staging hosts are behind auth | High | crawler_access.subdomains. Only publicly linked hosts: never guess-scan. |
| N7 | Release checklist | robots.txt, noindex, canonical and CDN rules checked on each release | Medium | Needs client data |

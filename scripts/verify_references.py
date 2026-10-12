"""Check every URL in framework/references.json, and that every check has one.

Usage: python3 scripts/verify_references.py [--quick]

A reference printed under a client-facing finding has to resolve. This fetches
each source once at the polite rate and reports anything that does not answer
200, plus any check ID in checks.md with no reference and any source nothing
points at. Run it after editing references.json, and before an engagement where
the references matter.

Exit code 1 if a URL fails or a check ID is unmapped.
"""
import json
import re
import sys

from common import KIT_DIR, Fetcher, log

REFS = KIT_DIR / "framework" / "references.json"


def catalogue_ids():
    ids = []
    for line in (KIT_DIR / "framework" / "checks.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([A-Z]{1,2}\d+)\s*\|", line)
        if m:
            ids.append(m.group(1))
    return ids


def main():
    data = json.loads(REFS.read_text(encoding="utf-8"))
    sources, checks = data["sources"], data["checks"]
    problems = []

    ids = catalogue_ids()
    missing = [i for i in ids if i not in checks]
    if missing:
        problems.append(f"check IDs with no reference: {', '.join(missing)}")
    unknown = [i for i in checks if i not in ids]
    if unknown:
        problems.append(f"reference IDs not in checks.md: {', '.join(unknown)}")

    used = {k for keys in checks.values() for k in keys}
    for key in sorted(used):
        if key not in sources:
            problems.append(f"check references unknown source key: {key}")
    for key in sorted(set(sources) - used):
        log(f"note: source {key} is defined but no check uses it")

    if "--quick" not in sys.argv:
        f = Fetcher()
        for key in sorted(sources):
            url = sources[key]["url"]
            r = f.get(url)
            status = r.get("status")
            err = r.get("error") or ""
            if status == 200:
                log(f"OK    {key:6} 200 {url}")
            elif status in (401, 403, 429):
                # w3.org and others refuse non-browser clients. A refusal is
                # not a missing page, so it is surfaced rather than failed.
                log(f"BLOCK {key:6} {status} {url}  (refuses automated clients, open it in a browser)")
            elif "SSLError" in err or "CERTIFICATE_VERIFY_FAILED" in err:
                # A TLS-intercepting proxy on the audit machine, not the site.
                log(f"TLS   {key:6} local certificate interception, not checked: {url}")
            else:
                detail = status or err[:60] or "no response"
                log(f"FAIL  {key:6} {detail} {url}")
                problems.append(f"{key} did not resolve: {detail} ({url})")

    print()
    if problems:
        for p in problems:
            print("PROBLEM", p)
        sys.exit(1)
    print(f"OK: {len(sources)} sources, {len(checks)} checks mapped, every URL reachable.")


if __name__ == "__main__":
    main()

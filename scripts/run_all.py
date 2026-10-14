"""Run every evidence-collection step in order.

Usage: python3 scripts/run_all.py example.com [--max-pages 50] [--link-check 120]
                                   [--delay 0.5] [--skip-render] [--skip-psi]

--delay sets the seconds to wait between requests, for every step. The default
is 0.5, which is the 2 requests per second ceiling. Raise it for a small host
that drops a client making several connections at once: --delay 5 is one
request every five seconds, slow but reliable on shared hosting.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def step(args, env=None):
    print(f"\n=== {' '.join(args)}", flush=True)
    r = subprocess.run([sys.executable, *args], cwd=HERE, env=env)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--max-pages", default="50")
    ap.add_argument("--link-check", default="120")
    ap.add_argument("--delay", type=float, default=None,
                    help="seconds between requests, for every step (default 0.5)")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--skip-psi", action="store_true")
    a = ap.parse_args()

    # Every step runs as its own process, so the delay travels in the
    # environment rather than as a flag each collector would have to accept.
    env = dict(os.environ)
    if a.delay is not None:
        if a.delay < 0:
            sys.exit("--delay cannot be negative")
        env["AUDIT_REQUEST_DELAY"] = str(a.delay)
        print(f"Request delay: {a.delay} s between requests "
              f"({1 / a.delay:.2f} per second)" if a.delay else
              "Request delay: none", flush=True)

    rc = step(["01_preflight.py", a.domain], env)
    if rc == 2:
        sys.exit("Site unreachable from this machine. Stop and report it; do not write findings.")
    if rc:
        sys.exit(rc)
    failures = []
    for s in (["02_crawler_access.py", a.domain],
              ["03_crawl.py", a.domain, "--max-pages", a.max_pages,
               "--link-check", a.link_check],
              ["04_server_checks.py", a.domain]):
        if step(s, env):
            failures.append(s[0])
    if not a.skip_psi and step(["05_performance.py", a.domain], env):
        failures.append("05_performance.py")
    if not a.skip_render and step(["06_render.py", a.domain], env):
        failures.append("06_render.py")
    print("\nDone. Evidence in out/<domain>/data/.", "Failed steps: " + ", ".join(failures) if failures else "All steps succeeded.")


if __name__ == "__main__":
    main()

"""Run every evidence-collection step in order.

Usage: python3 scripts/run_all.py example.com [--max-pages 150] [--skip-render] [--skip-psi]
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def step(args):
    print(f"\n=== {' '.join(args)}", flush=True)
    r = subprocess.run([sys.executable, *args], cwd=HERE)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--max-pages", default="150")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--skip-psi", action="store_true")
    a = ap.parse_args()
    rc = step(["01_preflight.py", a.domain])
    if rc == 2:
        sys.exit("Site unreachable from this machine. Stop and report it; do not write findings.")
    if rc:
        sys.exit(rc)
    failures = []
    for s in (["02_crawler_access.py", a.domain], ["03_crawl.py", a.domain, "--max-pages", a.max_pages],
              ["04_server_checks.py", a.domain]):
        if step(s):
            failures.append(s[0])
    if not a.skip_psi and step(["05_performance.py", a.domain]):
        failures.append("05_performance.py")
    if not a.skip_render and step(["06_render.py", a.domain]):
        failures.append("06_render.py")
    print("\nDone. Evidence in out/<domain>/data/.", "Failed steps: " + ", ".join(failures) if failures else "All steps succeeded.")


if __name__ == "__main__":
    main()

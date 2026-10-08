"""HTTP front end for the Wellows site audit kit.

Wraps the CLI collectors in a small API so an audit can be started, watched and
collected over HTTP. An audit takes far longer than any request timeout allows,
so every run happens in a background thread and the caller polls for status.

What this service does NOT do: write findings.json. That step is a judgement
call made against the evidence, so the service exposes the evidence and accepts
a findings.json upload, then builds the client report from it.

Environment:
  AUDIT_API_TOKEN        Required. Bearer token for every route except /healthz.
  AUDIT_ALLOWED_DOMAINS  Required. Comma-separated hosts this service may audit.
                         A host matches itself and its subdomains. "*" disables
                         the allowlist and is refused unless AUDIT_ALLOW_ANY=1.
  AUDIT_OUT_DIR          Where evidence and reports land. Use a mounted disk.
  AUDIT_MAX_CONCURRENT   Parallel audits. Default 1.
  PSI_API_KEY            Passed through to the PageSpeed step.
"""
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = KIT_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))
from common import OUT_ROOT, normalize_domain  # noqa: E402

LOG_DIR = OUT_ROOT / "_jobs"
MAX_CONCURRENT = int(os.environ.get("AUDIT_MAX_CONCURRENT", "1"))
_slots = threading.Semaphore(MAX_CONCURRENT)
_jobs = {}
_jobs_lock = threading.Lock()

app = FastAPI(title="Wellows site audit", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- auth, input

def require_token(request: Request):
    """Bearer auth. The service refuses to serve anything if no token is set."""
    expected = os.environ.get("AUDIT_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "AUDIT_API_TOKEN is not set on this service")
    sent = request.headers.get("authorization", "")
    if sent.lower().startswith("bearer "):
        sent = sent[7:]
    else:
        sent = request.query_params.get("token", "")
    if not sent or not secrets.compare_digest(sent, expected):
        raise HTTPException(401, "Bad or missing token")


def allowed_domains():
    raw = [d.strip().lower().strip(".") for d in
           os.environ.get("AUDIT_ALLOWED_DOMAINS", "").split(",")]
    return [d for d in raw if d]


def check_authorized(domain: str):
    """The kit audits only domains Wellows owns or is engaged to audit.

    A public endpoint that crawls any host on request is an open crawler, so the
    allowlist is required and the service fails closed without one.
    """
    allow = allowed_domains()
    if not allow:
        raise HTTPException(503, "AUDIT_ALLOWED_DOMAINS is not set on this service")
    if allow == ["*"]:
        if os.environ.get("AUDIT_ALLOW_ANY") == "1":
            return
        raise HTTPException(
            403, 'AUDIT_ALLOWED_DOMAINS="*" also needs AUDIT_ALLOW_ANY=1. '
                 "Audit only domains you own or are engaged to audit.")
    if not any(domain == a or domain.endswith("." + a) for a in allow):
        raise HTTPException(403, f"{domain} is not in AUDIT_ALLOWED_DOMAINS")


def job_or_404(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job")
    return job


def safe_path(root: Path, rel: str) -> Path:
    """Resolve rel under root, refusing anything that escapes it."""
    root = root.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(403, "Path outside the job directory")
    if not target.is_file():
        raise HTTPException(404, "No such file")
    return target


# ------------------------------------------------------------------- the work

def run_audit(job_id: str, domain: str, max_pages: int, skip_psi: bool, skip_render: bool):
    job = _jobs[job_id]
    log_path = LOG_DIR / f"{job_id}.log"
    cmd = [sys.executable, "run_all.py", domain, "--max-pages", str(max_pages)]
    if skip_psi:
        cmd.append("--skip-psi")
    if skip_render:
        cmd.append("--skip-render")
    with _slots:
        _set(job, status="running", started_at=_now())
        try:
            with log_path.open("w", encoding="utf-8") as log:
                proc = subprocess.run(cmd, cwd=SCRIPTS, stdout=log, stderr=subprocess.STDOUT,
                                      text=True, timeout=60 * 90)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _set(job, status="failed", error="Collection exceeded 90 minutes", finished_at=_now())
            return
        except Exception as e:  # noqa: BLE001
            _set(job, status="failed", error=str(e)[:500], finished_at=_now())
            return
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    if rc != 0 and "unreachable" in tail.lower():
        _set(job, status="unreachable", returncode=rc, finished_at=_now(),
             error="Preflight could not reach the site. No findings should be written from this run.")
    elif rc != 0:
        _set(job, status="failed", returncode=rc, finished_at=_now(),
             error="Collection exited non-zero. See the log.")
    else:
        _set(job, status="collected", returncode=rc, finished_at=_now())


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set(job, **kw):
    with _jobs_lock:
        job.update(kw)


# ------------------------------------------------------------------ the routes

class AuditRequest(BaseModel):
    domain: str
    max_pages: int = Field(150, ge=1, le=1000)
    skip_psi: bool = False
    skip_render: bool = False


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.post("/audits", dependencies=[Depends(require_token)], status_code=202)
def start_audit(req: AuditRequest):
    domain = normalize_domain(req.domain)
    if not domain:
        raise HTTPException(400, "Could not read a hostname from that value")
    check_authorized(domain)
    with _jobs_lock:
        busy = [j for j in _jobs.values()
                if j["domain"] == domain and j["status"] in ("queued", "running")]
    if busy:
        raise HTTPException(409, f"An audit of {domain} is already {busy[0]['status']}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "domain": domain, "status": "queued", "created_at": _now(),
           "max_pages": req.max_pages, "skip_psi": req.skip_psi, "skip_render": req.skip_render,
           "returncode": None, "error": None, "started_at": None, "finished_at": None}
    with _jobs_lock:
        _jobs[job_id] = job
    threading.Thread(target=run_audit, daemon=True,
                     args=(job_id, domain, req.max_pages, req.skip_psi, req.skip_render)).start()
    return job


@app.get("/audits", dependencies=[Depends(require_token)])
def list_audits():
    with _jobs_lock:
        return sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)


@app.get("/audits/{job_id}", dependencies=[Depends(require_token)])
def get_audit(job_id: str, log_lines: int = 40):
    job = dict(job_or_404(job_id))
    log_path = LOG_DIR / f"{job_id}.log"
    if log_path.exists():
        job["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-log_lines:]
    data = OUT_ROOT / job["domain"] / "data"
    job["evidence_files"] = sorted(p.name for p in data.glob("*")) if data.is_dir() else []
    job["report_ready"] = (OUT_ROOT / job["domain"] / "report" /
                           f"{job['domain']}-technical-audit.html").is_file()
    return job


@app.get("/audits/{job_id}/files/{rel:path}", dependencies=[Depends(require_token)])
def get_file(job_id: str, rel: str):
    job = job_or_404(job_id)
    return FileResponse(safe_path(OUT_ROOT / job["domain"], rel))


@app.post("/audits/{job_id}/findings", dependencies=[Depends(require_token)])
async def upload_findings(job_id: str, file: UploadFile):
    """Accept findings.json, then build the client report from it.

    build_report.py validates before it writes: every catalogue ID present once,
    every Issue carrying severity, evidence, impact and fix, no em dashes. Its
    failures come straight back so they can be fixed and re-uploaded.
    """
    job = job_or_404(job_id)
    domain = job["domain"]
    raw = await file.read()
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Not valid JSON: {e}")
    dest = OUT_ROOT / domain / "findings.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    proc = subprocess.run([sys.executable, "build_report.py", domain], cwd=SCRIPTS,
                          capture_output=True, text=True, timeout=300)
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        _set(job, status="findings_rejected")
        return JSONResponse(status_code=422, content={"built": False, "problems": output.splitlines()})
    _set(job, status="reported")
    return {"built": True, "report_url": f"/audits/{job_id}/report", "output": output.splitlines()}


@app.get("/audits/{job_id}/report", dependencies=[Depends(require_token)])
def get_report(job_id: str):
    job = job_or_404(job_id)
    domain = job["domain"]
    path = OUT_ROOT / domain / "report" / f"{domain}-technical-audit.html"
    if not path.is_file():
        raise HTTPException(404, "No report yet. Upload findings.json first.")
    return FileResponse(path, media_type="text/html")


@app.get("/", response_class=HTMLResponse)
def console():
    allow = allowed_domains()
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Wellows site audit</title>
<style>
 :root{{color-scheme:light dark;--fg:#111;--mut:#666;--line:#ddd;--bg:#fff}}
 @media(prefers-color-scheme:dark){{:root{{--fg:#eee;--mut:#999;--line:#333;--bg:#141414}}}}
 body{{font:15px/1.6 system-ui,sans-serif;max-width:52rem;margin:0 auto;padding:2rem 1rem;color:var(--fg);background:var(--bg)}}
 code,pre{{font-family:ui-monospace,monospace;font-size:13px}}
 pre{{background:color-mix(in srgb,var(--fg) 6%,transparent);padding:.75rem;border-radius:6px;overflow-x:auto}}
 td,th{{border-bottom:1px solid var(--line);padding:.4rem .6rem;text-align:left}}
 .mut{{color:var(--mut)}}
</style>
<h1>Wellows site audit</h1>
<p class="mut">Evidence collection over HTTP. Every route below needs
<code>Authorization: Bearer &lt;AUDIT_API_TOKEN&gt;</code>.</p>
<p>Allowed domains: <code>{", ".join(allow) if allow else "none set, audits will be refused"}</code></p>
<table>
<tr><th>Route</th><th>Does</th></tr>
<tr><td><code>POST /audits</code></td><td>Start a run. Body: <code>{{"domain":"example.com"}}</code></td></tr>
<tr><td><code>GET /audits/{{id}}</code></td><td>Status, log tail, evidence file list</td></tr>
<tr><td><code>GET /audits/{{id}}/files/data/crawl_summary.json</code></td><td>Any evidence file</td></tr>
<tr><td><code>POST /audits/{{id}}/findings</code></td><td>Upload findings.json, builds the report or returns the validation errors</td></tr>
<tr><td><code>GET /audits/{{id}}/report</code></td><td>The built client report</td></tr>
</table>
<pre>curl -X POST $HOST/audits -H "Authorization: Bearer $TOKEN" \\
     -H "Content-Type: application/json" -d '{{"domain":"example.com"}}'</pre>
<p class="mut">The service collects evidence. Writing findings.json is a judgement step
made against that evidence, not an automated one.</p>
</html>"""

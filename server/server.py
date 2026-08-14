import os
import time
import json
import uuid
import threading
import subprocess
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from io import BytesIO
import base64
import qrcode

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional

# ── config ────────────────────────────────────────────────────

RPC_PORT = 6800
RPC_SECRET = os.getenv("RPC_SECRET", "Kobir_pro_secret_2026")
BIND_PORT = int(os.getenv("PORT", "8000"))
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/app/downloads")
FILE_TTL = int(os.getenv("FILE_TTL", "0"))
API_KEY = os.getenv("API_KEY", "")
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "10"))
SERVER_NAME = os.getenv("SERVER_NAME", "MirrorPro")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = FastAPI(title=SERVER_NAME)
templates = Jinja2Templates(directory="templates")

# ── state ─────────────────────────────────────────────────────

tasks = {}
speed_log = {}
_rpc_id = 0
_lock = threading.Lock()


# ── aria2 daemon ──────────────────────────────────────────────

def start_aria2() -> bool:
    subprocess.run([
        "aria2c",
        "--enable-rpc",
        f"--rpc-listen-port={RPC_PORT}",
        f"--rpc-secret={RPC_SECRET}",
        f"--dir={DOWNLOAD_DIR}",
        f"--max-concurrent-downloads={MAX_CONCURRENT}",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--continue=true",
        "--file-allocation=none",
        "--daemon=true",
        "--quiet=true",
    ], capture_output=True, text=True)

    for _ in range(20):
        try:
            _rpc("aria2.getVersion")
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _rpc(method, params=None):
    global _rpc_id
    with _lock:
        _rpc_id += 1
        rid = str(_rpc_id)

    all_params = [f"token:{RPC_SECRET}"]
    if params:
        all_params.extend(params)

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": rid,
        "method": method,
        "params": all_params,
    }).encode()

    req = urllib.request.Request(
        f"http://localhost:{RPC_PORT}/jsonrpc",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())

    if "error" in result:
        raise RuntimeError(result["error"])
    return result.get("result")


# ── helpers ───────────────────────────────────────────────────

def fsize(b: int) -> str:
    b = float(b)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"


def fspeed(bps: int) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024**2:
        return f"{bps/1024:.1f} KB/s"
    return f"{bps/1024**2:.1f} MB/s"


def feta(sec: float) -> str:
    if sec <= 0:
        return "∞"
    if sec < 60:
        return f"{int(sec)}s"
    if sec < 3600:
        return f"{int(sec/60)}m {int(sec%60)}s"
    return f"{int(sec/3600)}h {int((sec%3600)/60)}m"


def fduration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{int(sec/60)}m {int(sec%60)}s"
    return f"{int(sec/3600)}h {int((sec%3600)/60)}m"


def extract_source(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return "unknown"


def extract_filename(url: str) -> str:
    path = urlparse(url).path
    name = os.path.basename(path)
    return name if name else "download"


def make_qr_b64(data: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#e4e4e7", back_color="#0a0a0f")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build_mirror_url(request: Request, filename: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/d/{filename}"


def get_avg_speed(gid: str) -> float:
    log = speed_log.get(gid, [])
    if not log:
        return 0.0
    return sum(s for _, s in log) / len(log)


def get_peak_speed(gid: str) -> int:
    log = speed_log.get(gid, [])
    if not log:
        return 0
    return max(s for _, s in log)


# ── auth ──────────────────────────────────────────────────────

def check_auth(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "invalid api key")
    return True


# ── cleanup ───────────────────────────────────────────────────

def cleanup_loop():
    while True:
        now = time.time()
        with _lock:
            for gid, meta in list(tasks.items()):
                ttl = meta.get("ttl", FILE_TTL)

                # TTL-based file + metadata cleanup
                if ttl > 0 and meta.get("completed_at"):
                    elapsed = now - meta["completed_at"]
                    if elapsed > ttl:
                        fp = meta.get("filepath")
                        if fp and os.path.exists(fp):
                            try:
                                os.remove(fp)
                            except Exception:
                                pass
                        tasks.pop(gid, None)
                        speed_log.pop(gid, None)

                # error/removed tasks — 1 hour after creation
                elif meta["status"] in ("error", "removed"):
                    if now - meta.get("created_at", now) > 3600:
                        tasks.pop(gid, None)
                        speed_log.pop(gid, None)

                # completed TTL=0 — metadata after 24h (file stays)
                elif meta["status"] == "complete" and ttl == 0:
                    if now - meta.get("completed_at", now) > 86400:
                        tasks.pop(gid, None)
                        speed_log.pop(gid, None)
        time.sleep(60)


# ── models ────────────────────────────────────────────────────

class MirrorRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    ttl: Optional[int] = None


# ── API endpoints ─────────────────────────────────────────────

@app.post("/api/mirror")
async def api_mirror(req: MirrorRequest, request: Request, _: bool = Depends(check_auth)):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid url de")

    source = extract_source(url)
    orig_name = req.filename or extract_filename(url)
    ttl_val = req.ttl if req.ttl is not None else FILE_TTL

    # BUG FIX #5: filename collision
    final_name = orig_name
    if os.path.exists(os.path.join(DOWNLOAD_DIR, final_name)):
        stem, ext = os.path.splitext(orig_name)
        final_name = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"

    aria_opts = {"out": final_name}
    try:
        gid = _rpc("aria2.addUri", [[url], aria_opts])
    except Exception as e:
        raise HTTPException(500, str(e))

    tasks[gid] = {
        "gid": gid,
        "url": url,
        "source": source,
        "filename": final_name,
        "filepath": None,
        "status": "active",
        "created_at": time.time(),
        "completed_at": None,
        "ttl": ttl_val,
        "size_total": 0,
        "size_done": 0,
    }
    speed_log[gid] = []

    return JSONResponse({
        "gid": gid,
        "status": "active",
        "filename": final_name,
        "source": source,
        "status_url": f"/status/{gid}",
        "api_status_url": f"/api/status/{gid}",
        "message": "ডাউনলোড শুরু হয়েছে",
    })


@app.get("/api/status/{gid}")
async def api_status(gid: str, request: Request, _: bool = Depends(check_auth)):
    if gid not in tasks:
        raise HTTPException(404, "gid পাওয়া যায়নি")

    meta = tasks[gid]

    try:
        st = _rpc("aria2.tellStatus", [gid])
    except Exception:
        if meta.get("filepath") and os.path.exists(meta["filepath"]):
            mirror = build_mirror_url(request, meta["filename"])
            sz = os.path.getsize(meta["filepath"])
            return JSONResponse({
                "status": "complete",
                "gid": gid,
                "filename": meta["filename"],
                "source": meta["source"],
                "source_url": meta["url"],
                "mirror_url": mirror,
                "size_bytes": sz,
                "size_human": fsize(sz),
                "download_duration": fduration(time.time() - meta["created_at"]),
                "created_at": datetime.fromtimestamp(meta["created_at"], tz=timezone.utc).isoformat(),
                "auto_delete": meta["ttl"] > 0,
                "expires_in_sec": max(0, int(meta["ttl"] - (time.time() - meta.get("completed_at", time.time())))) if meta["ttl"] > 0 else None,
            })
        raise HTTPException(404, "task নেই")

    state = st.get("status", "?")
    done = int(st.get("completedLength", "0"))
    total = int(st.get("totalLength", "0"))
    spd = int(st.get("downloadSpeed", "0"))

    if state == "active" and spd > 0:
        speed_log.setdefault(gid, []).append((time.time(), spd))
        if len(speed_log[gid]) > 60:
            speed_log[gid] = speed_log[gid][-60:]

    meta["size_done"] = done
    meta["size_total"] = total

    if state == "complete":
        files = st.get("files", [{}])
        filepath = files[0].get("path", "") if files else ""
        filename = os.path.basename(filepath) if filepath else meta["filename"]

        meta["status"] = "complete"
        meta["filepath"] = filepath
        meta["filename"] = filename
        meta["completed_at"] = time.time()

        mirror = build_mirror_url(request, filename)
        avg_spd = get_avg_speed(gid)
        peak_spd = get_peak_speed(gid)
        duration = meta["completed_at"] - meta["created_at"]

        expires = None
        if meta["ttl"] > 0:
            expires = max(0, int(meta["ttl"] - (time.time() - meta["completed_at"])))

        return JSONResponse({
            "status": "complete",
            "gid": gid,
            "filename": filename,
            "source": meta["source"],
            "source_url": meta["url"],
            "mirror_url": mirror,
            "size_bytes": total,
            "size_human": fsize(total),
            "download_duration": fduration(duration),
            "average_speed": fspeed(int(avg_spd)),
            "peak_speed": fspeed(peak_spd),
            "created_at": datetime.fromtimestamp(meta["created_at"], tz=timezone.utc).isoformat(),
            "completed_at": datetime.fromtimestamp(meta["completed_at"], tz=timezone.utc).isoformat(),
            "auto_delete": meta["ttl"] > 0,
            "expires_in_sec": expires,
        })

    if state in ("error", "removed"):
        meta["status"] = state
        return JSONResponse({
            "status": state,
            "gid": gid,
            "error": st.get("errorMessage", "unknown error"),
        })

    pct = (done / total * 100) if total > 0 else 0
    eta = (total - done) / spd if spd > 0 else 0
    avg_spd = get_avg_speed(gid)

    return JSONResponse({
        "status": "active",
        "gid": gid,
        "filename": meta["filename"],
        "source": meta["source"],
        "source_url": meta["url"],
        "progress_pct": round(pct, 1),
        "downloaded": fsize(done),
        "downloaded_bytes": done,
        "total": fsize(total),
        "total_bytes": total,
        "speed": fspeed(spd),
        "average_speed": fspeed(int(avg_spd)) if avg_spd > 0 else "—",
        "eta": feta(eta),
        "eta_sec": round(eta) if eta > 0 else None,
        "connections": 16,
        "created_at": datetime.fromtimestamp(meta["created_at"], tz=timezone.utc).isoformat(),
    })


@app.get("/api/list")
async def api_list(request: Request, _: bool = Depends(check_auth)):
    # BUG FIX #6: thread-safe snapshot
    with _lock:
        snapshot = dict(tasks)

    result = []
    for gid, meta in snapshot.items():
        item = {
            "gid": gid,
            "status": meta["status"],
            "filename": meta["filename"],
            "source": meta["source"],
            "source_url": meta["url"],
            "created_at": datetime.fromtimestamp(meta["created_at"], tz=timezone.utc).isoformat(),
        }
        if meta["status"] == "complete" and meta.get("filepath"):
            if os.path.exists(meta["filepath"]):
                sz = os.path.getsize(meta["filepath"])
                item["size_human"] = fsize(sz)
                item["size_bytes"] = sz
                item["mirror_url"] = build_mirror_url(request, meta["filename"])
                if meta["ttl"] > 0 and meta.get("completed_at"):
                    remaining = max(0, int(meta["ttl"] - (time.time() - meta["completed_at"])))
                    item["expires_in_sec"] = remaining
                    item["auto_delete"] = True
        elif meta["status"] == "active":
            item["downloaded"] = fsize(meta.get("size_done", 0))
            item["total"] = fsize(meta.get("size_total", 0))
        result.append(item)

    return JSONResponse({
        "server": SERVER_NAME,
        "total_tasks": len(result),
        "auto_delete_enabled": FILE_TTL > 0,
        "default_ttl": FILE_TTL,
        "tasks": result,
    })


@app.delete("/api/delete/{gid}")
async def api_delete(gid: str, _: bool = Depends(check_auth)):
    if gid not in tasks:
        raise HTTPException(404, "gid নেই")

    try:
        _rpc("aria2.remove", [gid])
    except Exception:
        pass

    with _lock:
        meta = tasks.pop(gid, {})
        speed_log.pop(gid, None)

    fp = meta.get("filepath")
    if fp and os.path.exists(fp):
        os.remove(fp)

    return JSONResponse({"deleted": gid, "filename": meta.get("filename", "")})


@app.get("/api/qr")
async def api_qr(url: str, _: bool = Depends(check_auth)):
    qr_b64 = make_qr_b64(url)
    return JSONResponse({"qr_b64": qr_b64, "url": url})


@app.get("/health")
async def health():
    try:
        ver = _rpc("aria2.getVersion")
        aria_ok = True
    except Exception:
        aria_ok = False

    active_count = sum(1 for m in tasks.values() if m["status"] == "active")
    complete_count = sum(1 for m in tasks.values() if m["status"] == "complete")

    return JSONResponse({
        "status": "ok" if aria_ok else "degraded",
        "aria2": "running" if aria_ok else "down",
        "server_name": SERVER_NAME,
        "active_downloads": active_count,
        "completed_files": complete_count,
        "auto_delete": FILE_TTL > 0,
        "ttl_seconds": FILE_TTL,
    })


# ── file serving ──────────────────────────────────────────────

@app.get("/d/{filename}")
async def serve_file(filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "bad filename")

    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "ফাইল নেই বা expire হয়ে গেছে")

    return FileResponse(
        filepath,
        filename=filename,
        media_type="application/octet-stream",
    )


# ── HTML pages ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "server_name": SERVER_NAME,
        "auto_delete": FILE_TTL > 0,
        "ttl_hours": round(FILE_TTL / 3600, 1) if FILE_TTL > 0 else 0,
        "api_key_required": bool(API_KEY),
    })


@app.get("/status/{gid}", response_class=HTMLResponse)
async def page_status(gid: str, request: Request):
    if gid not in tasks:
        raise HTTPException(404, "gid পাওয়া যায়নি")

    meta = tasks[gid]
    return templates.TemplateResponse("status.html", {
        "request": request,
        "gid": gid,
        "filename": meta["filename"],
        "source": meta["source"],
        "source_url": meta["url"],
        "server_name": SERVER_NAME,
        "api_key": API_KEY,
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "server_name": SERVER_NAME,
        "api_key": API_KEY,
        "auto_delete": FILE_TTL > 0,
    })


# ── startup ───────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    ok = start_aria2()
    if not ok:
        print("[!] aria2c চালু হয়নি")
        exit(1)
    ver = _rpc("aria2.getVersion")
    print(f"[*] aria2 {ver.get('version')} ready")
    print(f"[*] {SERVER_NAME} running on :{BIND_PORT}")
    print(f"[*] Auto-delete: {'ON (' + str(FILE_TTL) + 's)' if FILE_TTL > 0 else 'OFF'}")
    print(f"[*] Auth: {'ON' if API_KEY else 'OFF'}")
    threading.Thread(target=cleanup_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=BIND_PORT)

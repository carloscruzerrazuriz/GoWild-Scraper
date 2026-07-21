# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Servidor local de Cruzer.

Levanta un HTTP server en 127.0.0.1 (sólo loopback: nadie de la red puede
entrar) que sirve el frontend y expone las 3 herramientas. El progreso viaja al
navegador por **SSE** (Server-Sent Events): un stream de texto plano, sin
websockets ni dependencias extra.

Usa sólo la stdlib (http.server + threading) a propósito: menos dependencias =
un .exe más chico y un build de PyInstaller menos frágil.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import queue
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

UI_DIR = Path(__file__).resolve().parent / "ui"
OUTPUT_DIR = Path.home() / "Documents" / "Cruzer"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = OUTPUT_DIR / "_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Estado del job en curso (uno a la vez: son scrapes pesados).
JOB = {"running": False, "events": None, "result": None, "error": None, "tool": None}


def _emit(ev):
    q = JOB.get("events")
    if q is not None:
        q.put(ev)


def _run_job(tool, params):
    """Corre la herramienta en un hilo con su propio event loop."""
    from orchestrators import TOOLS
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        out = loop.run_until_complete(TOOLS[tool]["run"](params, _emit, OUTPUT_DIR))
        JOB["result"] = str(out)
        _emit({"type": "done", "file": Path(out).name, "path": str(out)})
    except Exception as e:  # noqa: BLE001
        JOB["error"] = str(e)
        _emit({"type": "error", "msg": str(e),
               "detail": traceback.format_exc()[-1200:]})
    finally:
        loop.close()
        JOB["running"] = False
        _emit({"type": "eof"})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencio en consola
        pass

    # ── helpers ──
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    # ── GET ──
    def do_GET(self):
        p = urlparse(self.path)
        route = p.path

        if route in ("/", "/index.html"):
            return self._file(UI_DIR / "index.html")
        if route.startswith("/ui/"):
            return self._file(UI_DIR / route[4:])

        if route == "/api/stores":
            from engines import maestra_sodimac as ms
            return self._json([{"id": s["id"], "name": s["name"],
                                "region": s["region"], "comuna": s["comuna"]}
                               for s in ms.ALL_STORES])

        if route == "/api/sections":
            # descubre el árbol (abre navegador una vez); puede tardar ~20s.
            # ?ferni=1 → sin entradas isLanding (Ferni no dedup entre subcats).
            try:
                from orchestrators import discover_sections_desktop
                q = parse_qs(p.query)
                incl = (q.get("ferni") or ["0"])[0] != "1"
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    tree = loop.run_until_complete(
                        discover_sections_desktop(lambda e: None, include_landing=incl))
                finally:
                    loop.close()
                return self._json(tree)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)

        if route == "/api/events":
            return self._sse()

        if route == "/api/status":
            return self._json({"running": JOB["running"], "tool": JOB["tool"],
                               "result": JOB["result"], "error": JOB["error"]})

        if route == "/api/download":
            q = parse_qs(p.query)
            f = unquote((q.get("f") or [""])[0])
            path = Path(f)
            if not path.is_file() or OUTPUT_DIR not in path.resolve().parents:
                return self._json({"error": "archivo no encontrado"}, 404)
            data = path.read_bytes()
            return self._send(200, data,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": f'attachment; filename="{path.name}"'})

        if route == "/api/outputs":
            files = sorted(OUTPUT_DIR.glob("*.xlsx"), key=lambda f: -f.stat().st_mtime)[:20]
            return self._json([{"name": f.name, "path": str(f),
                                "size": f.stat().st_size} for f in files])

        return self._json({"error": "not found"}, 404)

    def _file(self, path: Path):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return self._send(200, path.read_bytes(), ctype)

    def _sse(self):
        q = queue.Queue()
        JOB["events"] = q
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # evita que el proxy corte
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                if ev.get("type") == "eof":
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ── POST ──
    def do_POST(self):
        p = urlparse(self.path)

        if p.path == "/api/upload":
            # el archivo llega crudo; el nombre va en el header X-Filename
            name = self.headers.get("X-Filename") or "entrada.xlsx"
            dest = UPLOAD_DIR / f"{name}"
            dest.write_bytes(self._body())
            return self._json({"path": str(dest), "name": name})

        if p.path == "/api/run":
            if JOB["running"]:
                return self._json({"error": "Ya hay un proceso corriendo."}, 409)
            payload = json.loads(self._body() or b"{}")
            tool = payload.get("tool")
            from orchestrators import TOOLS
            if tool not in TOOLS:
                return self._json({"error": f"herramienta desconocida: {tool}"}, 400)
            JOB.update(running=True, result=None, error=None, tool=tool)
            threading.Thread(target=_run_job, args=(tool, payload.get("params") or {}),
                             daemon=True).start()
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def serve(port=8733):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd

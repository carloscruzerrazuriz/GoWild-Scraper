# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
# === Sistema ÚNICO de checkpoints (reanudación) para todas las herramientas ===

"""Módulo único de checkpoints para todas las herramientas del proyecto.

Antes cada launcher (MK7 `mk7`, Sección `maestra` ×3 retailers, Mayoristas
`mayoristas`, Ferni Maestra `ferni_maestra`) tenía su PROPIA copia de la
maquinaria de checkpoints, y habían DIVERGIDO — con bugs reales:

  1. **El `.meta.json` no refrescaba su mtime al reanudar** (Sección/Ferni):
     la limpieza TTL de 12 h borraba archivo-por-archivo, así que en un run
     reanudado cruzando las 12 h del PRIMER arranque el `.meta` (viejo) se
     purgaba antes que el `.jsonl` (fresco por el append) → el panel de
     reanudación (que exige el meta) dejaba de mostrarlo aunque las filas
     seguían en disco → "se borran si se corta más de una vez".
  2. **Fallback silencioso a filesystem efímero**: si el montaje de Drive
     fallaba, los checkpoints iban a `/content` y se perdían justo en la
     desconexión que debían sobrevivir → "no se generan".
  3. **`.jsonl` creado perezosamente** (Ferni): un run cortado antes de la 1ª
     fila no ofrecía reanudar (el panel exigía que el `.jsonl` existiera).
  4. **Mayoristas sin TTL y sin borrar los checkpoints terminados** → basura
     acumulándose para siempre en el Drive del usuario.
  5. **MK7 duplicaba filas** si una tienda se cortaba a mitad (se re-scrapeaba
     completa y se re-anexaban sus filas).

Este módulo unifica todo en UNA implementación robusta. Claves de diseño:

  • **TTL por RUN, no por archivo**: `purge_expired` agrupa los archivos por
    `run_id` y borra el run completo solo si el MÁS NUEVO de sus archivos
    superó el TTL. Un run reanudado (jsonl fresco) protege su meta → fix #1.
  • **Fallback ruidoso**: `resolve_dir` devuelve un flag `ephemeral`; el
    launcher muestra una advertencia visible → fix #2.
  • **`.jsonl` eager**: `start_run`/`ensure_jsonl` crean el archivo vacío al
    inicio, y `list_runs` tolera su ausencia → fix #3.
  • **Cleanup + TTL disponibles para todas** → fix #4.
  • **`load_rows(..., dedup_keys=...)`** deduplica al recargar → fix #5.

Nomenclatura ESTÁNDAR de archivos (por run, dentro del dir de cada herramienta):
    {run_id}.meta.json   payload libre del launcher (incluye 'finished': bool)
    {run_id}.jsonl       filas incrementales (una por línea)
    {run_id}.done.tsv    (opcional) pares (unidad, clave) ya completados

API pública (funcional, para que el wiring de cada launcher sea mecánico):
    resolve_dir(in_colab, drive_subdir, local_name)      -> (Path, ephemeral: bool)
    purge_expired(partial_dir, ttl_secs=12*3600)         -> None
    start_run(partial_dir, run_id, meta)                 -> None   (escribe meta + jsonl vacío)
    write_meta(partial_dir, run_id, meta)                -> None   (crea/refresca; toca mtime)
    touch_run(partial_dir, run_id)                       -> None   (refresca mtime de todos los archivos)
    append_row(partial_dir, run_id, row)                 -> None
    load_rows(partial_dir, run_id, dedup_keys=None)      -> list[dict]
    append_done(partial_dir, run_id, unit, key)          -> None
    read_done(partial_dir, run_id)                       -> set[tuple[str,str]]
    read_meta(partial_dir, run_id)                       -> dict | None
    mark_finished(partial_dir, run_id)                   -> None
    cleanup_run(partial_dir, run_id)                     -> None
    list_runs(partial_dir, unfinished_only=True)         -> list[(run_id, meta, rows, done)]
    ephemeral_warning_html(tool_name)                    -> str
"""

import json as _json
import os as _os
import time as _time
from pathlib import Path

DEFAULT_TTL_SECS = 12 * 3600  # 12 horas

_SUFFIXES = (".meta.json", ".jsonl", ".done.tsv")


# ─────────────────────────────────────  Rutas  ─────────────────────────────

def meta_path(partial_dir, run_id):  return Path(partial_dir) / f"{run_id}.meta.json"
def jsonl_path(partial_dir, run_id): return Path(partial_dir) / f"{run_id}.jsonl"
def done_path(partial_dir, run_id):  return Path(partial_dir) / f"{run_id}.done.tsv"


def resolve_dir(*, in_colab, drive_subdir, local_name):
    """Resuelve el directorio de checkpoints. Devuelve (Path, ephemeral).

    En Colab intenta montar Drive y usar `MyDrive/{drive_subdir}` (persistente,
    sobrevive reinicios de la VM). Si el montaje falla — o no estamos en Colab —
    cae a un dir local `cwd/{local_name}` y marca `ephemeral=True` para que el
    launcher AVISE que los checkpoints no sobrevivirán a un reinicio (fix #2:
    antes el fallback era silencioso y el usuario creía que "no se generaban").
    """
    if in_colab:
        try:
            from google.colab import drive as _drive
            if not _os.path.isdir("/content/drive/MyDrive"):
                _drive.mount("/content/drive", force_remount=False)
            d = Path("/content/drive/MyDrive") / drive_subdir
            d.mkdir(parents=True, exist_ok=True)
            return d, False
        except Exception:
            pass
    d = Path.cwd() / local_name
    d.mkdir(parents=True, exist_ok=True)
    # Fuera de Colab NO es "efímero problemático" (el disco local persiste); solo
    # marcamos efímero cuando estábamos en Colab y el Drive falló.
    return d, bool(in_colab)


def ephemeral_warning_html(tool_name=""):
    return (
        "<div style='background:#fdecea;border-left:4px solid #c0392b;"
        "padding:.7rem 1rem;margin:.4rem 0;border-radius:6px;font-family:sans-serif;'>"
        "⚠️ <b>No se pudo montar Google Drive.</b> Los checkpoints se guardarán en "
        "el disco temporal de esta sesión y <b>se perderán si se reinicia el "
        "entorno</b>. Para reanudación segura tras un corte, vuelve a ejecutar "
        "autorizando el acceso a Drive.</div>"
    )


# ───────────────────────────────────  Limpieza TTL  ────────────────────────

def _run_id_of(path):
    name = path.name
    for suf in _SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return None


def purge_expired(partial_dir, ttl_secs=DEFAULT_TTL_SECS):
    """Borra runs cuyo archivo MÁS NUEVO superó el TTL (fix #1).

    Agrupa por run_id y toma el mtime máximo del run. Así un run reanudado
    (jsonl/done frescos) NO pierde su `.meta.json` viejo — antes cada archivo
    se evaluaba por separado y el meta congelado se purgaba primero, dejando
    huérfanas las filas y ocultando el checkpoint del panel de reanudación.
    """
    d = Path(partial_dir)
    now = _time.time()
    newest = {}   # run_id -> max mtime
    files = {}    # run_id -> [paths]
    for suf in _SUFFIXES:
        for p in d.glob(f"*{suf}"):
            rid = _run_id_of(p)
            if not rid:
                continue
            try:
                mt = p.stat().st_mtime
            except Exception:
                continue
            newest[rid] = max(newest.get(rid, 0), mt)
            files.setdefault(rid, []).append(p)
    for rid, mt in newest.items():
        if now - mt > ttl_secs:
            for p in files.get(rid, []):
                try: p.unlink()
                except Exception: pass


# ─────────────────────────────────────  Meta  ──────────────────────────────

def write_meta(partial_dir, run_id, meta):
    """Escribe (o refresca) el `.meta.json`. Refrescar toca el mtime → protege
    el run de la purga TTL mientras siga activo."""
    try:
        meta_path(partial_dir, run_id).write_text(
            _json.dumps(meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def read_meta(partial_dir, run_id):
    p = meta_path(partial_dir, run_id)
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def mark_finished(partial_dir, run_id):
    m = read_meta(partial_dir, run_id)
    if m is None:
        return
    m["finished"] = True
    write_meta(partial_dir, run_id, m)


def touch_run(partial_dir, run_id):
    """Refresca el mtime de todos los archivos del run (usar al reanudar para
    que el TTL cuente desde ahora)."""
    now = _time.time()
    for fn in (meta_path, jsonl_path, done_path):
        p = fn(partial_dir, run_id)
        if p.exists():
            try: _os.utime(p, (now, now))
            except Exception: pass


# ───────────────────────────────────  Filas (jsonl)  ───────────────────────

def ensure_jsonl(partial_dir, run_id):
    """Crea el `.jsonl` vacío si no existe (fix #3: creación EAGER para que un
    run cortado antes de la 1ª fila igual ofrezca reanudar)."""
    p = jsonl_path(partial_dir, run_id)
    if not p.exists():
        try: p.touch()
        except Exception: pass


def start_run(partial_dir, run_id, meta):
    """Inicia un run fresco: escribe el meta y crea el jsonl vacío (eager)."""
    write_meta(partial_dir, run_id, meta)
    ensure_jsonl(partial_dir, run_id)


def append_row(partial_dir, run_id, row):
    try:
        with open(jsonl_path(partial_dir, run_id), "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def load_rows(partial_dir, run_id, dedup_keys=None):
    """Carga las filas del `.jsonl`. Si `dedup_keys` (lista de nombres de
    columna) se pasa, descarta filas repetidas por esa clave compuesta —
    fix #5 (MK7 re-anexaba filas de una tienda re-scrapeada tras un corte)."""
    rows = []
    p = jsonl_path(partial_dir, run_id)
    if not p.exists():
        return rows
    seen = set()
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = _json.loads(line)
                except Exception:
                    continue
                if dedup_keys:
                    k = tuple(str(r.get(c, "")) for c in dedup_keys)
                    if k in seen:
                        continue
                    seen.add(k)
                rows.append(r)
    except Exception:
        pass
    return rows


# ───────────────────────────────────  Done (pares)  ────────────────────────

def append_done(partial_dir, run_id, unit, key):
    try:
        with open(done_path(partial_dir, run_id), "a", encoding="utf-8") as f:
            f.write(f"{unit}\t{key}\n")
    except Exception:
        pass


def read_done(partial_dir, run_id):
    p = done_path(partial_dir, run_id)
    done = set()
    if not p.exists():
        return done
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                done.add((parts[0], parts[1]))
    except Exception:
        pass
    return done


# ─────────────────────────────────────  Cleanup / listado  ─────────────────

def cleanup_run(partial_dir, run_id):
    for fn in (meta_path, jsonl_path, done_path):
        p = fn(partial_dir, run_id)
        try:
            if p.exists(): p.unlink()
        except Exception: pass


def list_runs(partial_dir, *, unfinished_only=True, dedup_keys=None):
    """Lista runs reanudables, más reciente primero.

    Devuelve [(run_id, meta, prior_rows, done_set)]. Requiere SOLO el
    `.meta.json` (el `.jsonl` es opcional — si falta, prior_rows=[]); fix #3.
    """
    d = Path(partial_dir)
    out = []
    metas = sorted(d.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for m in metas:
        rid = _run_id_of(m)
        if not rid:
            continue
        try:
            meta = _json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            continue
        if unfinished_only and meta.get("finished"):
            continue
        rows = load_rows(d, rid, dedup_keys=dedup_keys)
        done = read_done(d, rid)
        out.append((rid, meta, rows, done))
    return out

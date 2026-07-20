# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Puente entre los engines y la app de escritorio.

Los engines de `engines/` son UI-agnósticos, así que la app de escritorio los
reusa TAL CUAL (misma lógica que los Colab: mismos selectores, misma zona, mismo
Excel). Este módulo sólo aporta:

  1. Una API uniforme para las 3 herramientas: `run(params, emit) -> ruta_excel`.
  2. La traducción de los eventos de cada engine a un stream único (`emit`) que
     el servidor manda al frontend por SSE.
  3. El loop tienda×subcategoría de Maestra Sección, que en Colab vive dentro
     del launcher de ipywidgets y por eso no era reusable.

DIFERENCIAS A PROPÓSITO vs Colab (son la razón de ser de la app):
  - **Sin checkpoints**: no hay VM efímera que se caiga, así que no se monta
    Drive ni se persisten parciales. Un corte se reintenta y ya.
  - **Paralelismo agresivo**: corriendo desde el PC del usuario la IP es
    residencial (Cloudflare es mucho menos hostil que con las IPs de Google) y
    no hay límite de sesión, así que Fast usa más workers que en Colab.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

# Paralelismo local: más agresivo que en Colab (ver docstring).
FAST_WORKERS = 12


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", str(name)).strip().replace(" ", "_") or "salida"


# ── 1. MK7 — Buscador por SKU ───────────────────────────────────────────────
async def run_mk7(params, emit, outdir: Path):
    """params: {input_path, store_ids, screenshots}. Devuelve la ruta del Excel."""
    from engines import sodimac_engine as se

    stores = [s for s in se.ALL_STORES if s["id"] in set(params["store_ids"])]
    if not stores:
        raise ValueError("No seleccionaste ninguna tienda.")

    df, desc_col, sku_col, easy_col = se.read_input(params["input_path"])
    skus = [str(v).strip() for v in df[sku_col].tolist() if str(v).strip()]
    skus = [s for s in dict.fromkeys(skus) if s.isdigit()]  # dedup + sólo numéricos
    if not skus:
        raise ValueError("El archivo no tiene SKUs numéricos válidos.")

    emit({"type": "info", "msg": f"{len(skus)} SKUs · {len(stores)} tienda(s)"})
    shots = outdir / "_shots" if params.get("screenshots") else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    matches = await se.search_skus_mk6(
        skus, stores, headless=True, screenshot_dir=(str(shots) if shots else None),
        progress_cb=_zone_progress(emit, len(stores), {"zone": 0}))

    if not matches:
        raise RuntimeError("No se encontró ningún SKU en las tiendas seleccionadas.")

    out = outdir / f"MK7_Sodimac_{_ts()}.xlsx"
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(matches)} filas)…"})
    se.write_output(df, desc_col, sku_col, easy_col, matches, str(out), stores=stores)
    return out


# ── 2. Maestra Sección ──────────────────────────────────────────────────────
class _NullProg:
    """Los engines esperan un objeto de progreso estilo rich; acá no aplica."""
    def update(self, *a, **k): pass
    def advance(self, *a, **k): pass


async def discover_sections_desktop(emit, include_landing=True):
    """Descubre el árbol de secciones (abre el navegador una vez).

    `include_landing=False` para Ferni: su motor deduplica sólo DENTRO de cada
    subcategoría, así que las entradas "Todo X" (que hacen roll-up de sus
    hermanas) le duplicarían filas. Mismo criterio que su launcher de Colab.
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_sodimac as ms

    emit({"type": "info", "msg": "Abriendo navegador y descubriendo secciones…"})
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=ms.USER_AGENT,
                                      viewport={"width": 1280, "height": 900})
            pg = await ctx.new_page()
            tree = await ms.discover_sections(pg, include_landing=include_landing)
        finally:
            await b.close()
    return [{"section": sec, "subcats": [{"name": n, "url": u} for n, u in subs]}
            for sec, subs in tree]


async def run_seccion(params, emit, outdir: Path):
    """params: {section, subcats:[{name,url}], store_ids, only_sodimac, screenshots}."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_sodimac as ms

    stores = [s for s in ms.ALL_STORES if s["id"] in set(params["store_ids"])]
    subcats = [(s["name"], s["url"]) for s in params["subcats"]]
    if not stores or not subcats:
        raise ValueError("Falta seleccionar tienda(s) o subcategoría(s).")

    section_name = params.get("section") or "Sección"
    only_sod = not params.get("include_non_sodimac")
    shots = params.get("screenshots", False)
    shot_dir = None
    if shots:
        shot_dir = outdir / "_shots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        ms.SCREENSHOT_DIR = shot_dir

    all_rows = []
    total_units = len(stores) * len(subcats)
    unit = 0
    prog = _NullProg()

    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=ms.USER_AGENT,
                                      viewport={"width": 1280, "height": 900},
                                      color_scheme="light")
            page = await ctx.new_page()
            for store in stores:
                emit({"type": "info", "msg": f"Fijando zona: {store['name']}…"})
                ok = await ms.set_zone_with_retry(page, store["region"], store["comuna"])
                if not ok:
                    emit({"type": "warn", "msg": f"No se pudo fijar zona en {store['name']}, se salta."})
                    unit += len(subcats)
                    continue
                # dedup por SKU dentro de cada tienda (igual que el Colab)
                seen = {r["SKU"] for r in all_rows
                        if r.get("Tienda") == store["id"] and r.get("SKU")}
                for sc_name, sc_url in subcats:
                    unit += 1
                    emit({"type": "progress", "phase": "subcat", "done": unit,
                          "total": total_units, "msg": f"{store['name']} · {sc_name}"})
                    res = await ms.scrape_subcat(
                        page, section_name, sc_name, sc_url, prog, None,
                        capture_screenshots=shots, only_sodimac=only_sod,
                        auto_breadcrumb=(section_name == "Custom"))
                    for r in res.get("rows", []):
                        if only_sod and "SODIMAC" not in (r.get("Vendedor") or "").upper():
                            continue
                        sku = r.get("SKU")
                        if not sku or sku in seen:
                            continue
                        seen.add(sku)
                        all_rows.append({"Tienda": store["id"],
                                         "Nombre Tienda": store["name"], **r})
                    emit({"type": "count", "rows": len(all_rows)})
        finally:
            await b.close()

    if not all_rows:
        raise RuntimeError("No se obtuvo ninguna fila.")
    out = outdir / f"Seccion_{_safe(section_name)}_{_ts()}.xlsx"
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(all_rows)} filas)…"})
    ms.write_excel(all_rows, str(out), with_images=shots)
    return out


# ── 3. Fast — Precios por mayor (browserless) ───────────────────────────────
async def run_fast(params, emit, outdir: Path):
    """params: {store_ids, sections:[str]|None, url:str|None, wholesale_only}."""
    from engines import mayoristas_fast as mf
    from engines import maestra_sodimac as ms

    stores = [s for s in ms.ALL_STORES if s["id"] in set(params["store_ids"])]
    if not stores:
        raise ValueError("No seleccionaste ninguna tienda.")
    wholesale_only = params.get("wholesale_only", True)
    url_scope = (params.get("url") or "").strip()
    sections = params.get("sections") or None

    all_rows, report = [], []
    for i, store in enumerate(stores, 1):
        emit({"type": "info", "msg": f"[{i}/{len(stores)}] {store['name']}: fijando zona…"})
        if url_scope:
            cookie = await mf.fetch_zone_cookie(store, headless=True)
            tree = [("URL personalizada", [("URL personalizada", url_scope)])]
        else:
            cookie, tree = await mf.open_session(store, headless=True)
        if not cookie or not tree:
            emit({"type": "warn", "msg": f"No se pudo preparar {store['name']}, se salta."})
            continue
        if sections:
            wanted = set(sections)
            tree = [(sec, subs) for sec, subs in tree if sec in wanted]
        n_sub = sum(len(s) for _, s in tree)
        emit({"type": "info", "msg": f"{store['name']}: barriendo {n_sub} subcategorías…"})

        def subcat_cb(done, total, sec, name, kept, scanned, status=None):
            emit({"type": "progress", "phase": "subcat", "done": done, "total": total,
                  "msg": f"{sec[:22]} · {name[:22]}"})

        rows = await asyncio.to_thread(
            mf.scrape_all_wholesale, cookie, tree, store,
            wholesale_only=wholesale_only, only_sodimac=True,
            subcat_cb=subcat_cb, workers=FAST_WORKERS, report=report)
        all_rows.extend(rows)
        emit({"type": "count", "rows": len(all_rows)})

    if report:
        emit({"type": "warn",
              "msg": f"{len(report)} categoría(s) no se pudieron leer completas "
                     f"(error de red persistente)."})
    if not all_rows:
        raise RuntimeError("No se obtuvo ninguna fila.")
    tag = "mayoristas" if wholesale_only else "catalogo"
    out = outdir / f"Fast_{tag}_{_ts()}.xlsx"
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(all_rows)} filas)…"})
    ms.write_excel(all_rows, str(out), columns=mf.OUTPUT_COLS, with_images=False)
    return out


# ── 4. Ferni — puertas por SKU ──────────────────────────────────────────────
def _zone_progress(emit, total_zones, state):
    """Traductor de eventos compartido: MK7 y Ferni SKU emiten los mismos."""
    def cb(ev):
        e = ev.get("event")
        if e == "zone_start":
            state["zone"] += 1
            emit({"type": "progress", "phase": "zona",
                  "done": state["zone"] - 1, "total": total_zones,
                  "msg": f"Tienda {state['zone']}/{total_zones}: {ev['store']['name']}"})
        elif e == "batch_done":
            emit({"type": "progress", "phase": "lote",
                  "done": ev.get("batches_done_in_zone", 0),
                  "total": ev.get("total_batches_in_zone", 1),
                  "msg": f"{ev['store']['name']} · lote "
                         f"{ev.get('batches_done_in_zone')}/{ev.get('total_batches_in_zone')}"})
        elif e == "zone_end" and ev.get("zone_failed"):
            emit({"type": "warn", "msg": f"No se pudo fijar zona en {ev['store']['name']}"})
    return cb


async def run_ferni_sku(params, emit, outdir: Path):
    """params: {input_path, store_ids, screenshots}. Puertas: 1 fila por medida."""
    from engines import ferni_sodimac as fs

    stores = fs.stores_by_ids(params["store_ids"])
    if not stores:
        raise ValueError("No seleccionaste ninguna tienda.")
    df, desc_col, sku_col, easy_col = fs.read_input(params["input_path"])
    skus = [str(v).strip() for v in df[sku_col].tolist() if str(v).strip()]
    skus = [s for s in dict.fromkeys(skus) if s.isdigit()]
    if not skus:
        raise ValueError("El archivo no tiene SKUs numéricos válidos.")

    emit({"type": "info", "msg": f"{len(skus)} SKUs de puertas · {len(stores)} tienda(s)"})
    shots = params.get("screenshots", False)
    shot_dir = (outdir / "_shots") if shots else None
    if shot_dir:
        shot_dir.mkdir(parents=True, exist_ok=True)

    matches = await fs.search_doors(
        skus, stores, headless=True,
        screenshot_dir=(str(shot_dir) if shot_dir else None),
        progress_cb=_zone_progress(emit, len(stores), {"zone": 0}))
    if not matches:
        raise RuntimeError("No se encontró ninguna puerta en las tiendas seleccionadas.")

    out = outdir / f"Ferni_SKU_{_ts()}.xlsx"
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(matches)} filas)…"})
    fs.write_output(df, desc_col, sku_col, easy_col, matches, str(out),
                    stores=stores, embed_images=shots)
    return out


# ── 5. Ferni Sección — puertas y más, por categoría ─────────────────────────
async def run_ferni_seccion(params, emit, outdir: Path):
    """params: {section, subcats:[{name,url}], store_ids, screenshots}."""
    from engines import ferni_maestra_sodimac as fm

    from engines import maestra_sodimac as ms
    stores = [s for s in ms.ALL_STORES if s["id"] in set(params["store_ids"])]
    section_name = params.get("section") or "Sección"
    subcats = [(section_name, s["name"], s["url"]) for s in params["subcats"]]
    if not stores or not subcats:
        raise ValueError("Falta seleccionar tienda(s) o subcategoría(s).")

    shots = params.get("screenshots", False)
    shot_dir = (outdir / "_shots") if shots else None
    if shot_dir:
        shot_dir.mkdir(parents=True, exist_ok=True)

    total = len(stores) * len(subcats)
    state = {"n": 0, "rows": 0}

    def progress_cb(ev):
        # Nombres reales emitidos por ferni_maestra_sodimac.scrape_maestra
        e = ev.get("event")
        store = (ev.get("store") or {}).get("name", "")
        if e == "subcat_start":
            emit({"type": "progress", "phase": "subcat", "done": state["n"], "total": total,
                  "msg": f"{store} · {ev.get('subcat', '')}"})
        elif e == "subcat_done":
            state["n"] += 1
            emit({"type": "progress", "phase": "subcat", "done": state["n"], "total": total,
                  "msg": f"{store} · {ev.get('subcat', '')}"})
        elif e == "zone_end" and ev.get("zone_failed"):
            emit({"type": "warn", "msg": f"No se pudo fijar zona en {store}"})
        elif e == "browser_error":
            emit({"type": "warn", "msg": f"Navegador: {ev.get('msg', '')}"})

    def on_row(_r):
        state["rows"] += 1
        if state["rows"] % 25 == 0:
            emit({"type": "count", "rows": state["rows"]})

    emit({"type": "info", "msg": f"{len(subcats)} subcat(s) × {len(stores)} tienda(s)"})
    rows = await fm.scrape_maestra(
        subcats, stores, headless=True,
        screenshot_dir=(str(shot_dir) if shot_dir else None),
        progress_cb=progress_cb, on_row=on_row)
    if not rows:
        raise RuntimeError("No se obtuvo ninguna fila.")

    emit({"type": "count", "rows": len(rows)})
    out = outdir / f"Ferni_Seccion_{_safe(section_name)}_{_ts()}.xlsx"
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(rows)} filas)…"})
    fm.write_excel(rows, str(out), with_images=shots)
    return out


TOOLS = {
    "mk7":          {"label": "MK7 · Buscador por SKU",   "run": run_mk7},
    "seccion":      {"label": "Maestra Sección",          "run": run_seccion},
    "fast":         {"label": "Fast · Precios por mayor", "run": run_fast},
    "ferni_sku":    {"label": "Ferni · Puertas por SKU",  "run": run_ferni_sku},
    "ferni_seccion": {"label": "Ferni · Sección",         "run": run_ferni_seccion},
}

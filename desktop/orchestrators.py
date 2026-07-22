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
# Presupuesto TOTAL de workers de Fast repartido entre los jobs Fast activos
# (el server calcula params["_workers"] al lanzar). Evita que 3× Fast disparen
# 36 requests concurrentes a Sodimac → 429/bloqueo de Cloudflare.
FAST_WORKER_BUDGET = 12

# UA propio: `maestra_sodimac` no exporta USER_AGENT (sí lo hace sodimac_engine).
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", str(name)).strip().replace(" ", "_") or "salida"


def _outname(base: str, tag: str) -> str:
    """Nombre de Excel único por job: base_TIMESTAMP[_tag].xlsx.
    El `tag` (id corto del job) evita colisiones cuando 2 jobs de la misma
    herramienta terminan en el mismo segundo."""
    return f"{base}_{_ts()}" + (f"_{tag}" if tag else "") + ".xlsx"


def _shots_dir(outdir: Path, tag: str):
    """Carpeta de screenshots aislada por job (no se pisan entre paralelos)."""
    d = outdir / "_shots" / (tag or "run")
    d.mkdir(parents=True, exist_ok=True)
    return d


_REPO_ROOT = Path(__file__).resolve().parent.parent  # desktop/ → raíz del repo


def _colab_mk7_template():
    """Devuelve los BYTES EXACTOS del formato de carga del Colab (MK7).

    Fuente única de verdad: el blob base64 embebido en launchers/mk7.py
    (`_FORMATO_CARGA_B64`). Así el desktop entrega el MISMO archivo que el
    Colab (5 columnas: SKU Easy · Desc. Producto · SKU Sodimac · SKU Falabella
    · SKU Construmart) y nunca diverge. Lanza si no lo encuentra (para no
    servir en silencio un formato distinto).
    """
    import re
    src = (_REPO_ROOT / "launchers" / "mk7.py").read_text(encoding="utf-8")
    m = re.search(r'_FORMATO_CARGA_B64\s*=\s*"([^"]+)"', src)
    if not m:
        raise RuntimeError("No encontré _FORMATO_CARGA_B64 en launchers/mk7.py")
    import base64
    return base64.b64decode(m.group(1))


def build_template_bytes(tool: str):
    """Devuelve (nombre_archivo, bytes .xlsx) del 'formato de carga'.

    - mk7: bytes EXACTOS del template del Colab (5 columnas), no una copia.
    - ferni_sku: mismo diseño que el _download_formato del Colab (3 columnas,
      ejemplos de puertas): cabecera #334E68, freeze A2, SKU como texto.
    """
    if tool != "ferni_sku":  # mk7
        return "formato_carga.xlsx", _colab_mk7_template()

    import io
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter
    rows = [["SKU Easy", "Desc. Producto", "SKU Sodimac"],
            ["E001", "Puerta Madera Terciada Carpintera 90x200 (ejemplo)", "139566229"],
            ["E002", "Puerta MDF Milano 60x200 (ejemplo, oferta)", "120822458"],
            ["E003", "Puerta Madera Terciada Carpintera 75x200 (ejemplo)", "139566225"]]
    wb = Workbook(); ws = wb.active; ws.title = "SKUs"
    for r in rows:
        ws.append(r)
    fill = PatternFill("solid", fgColor="334E68")
    font = Font(color="FFFFFF", bold=True)
    align = Alignment(horizontal="center", vertical="center")
    for c in range(1, 4):
        cell = ws.cell(row=1, column=c)
        cell.fill = fill; cell.font = font; cell.alignment = align
    for i, w in enumerate((12, 55, 16), 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for ci in (1, 3):
        for row in ws.iter_rows(min_row=2, min_col=ci, max_col=ci):
            for cell in row:
                cell.number_format = "@"
    ws.freeze_panes = "A2"
    buf = io.BytesIO(); wb.save(buf)
    return "formato_carga_puertas.xlsx", buf.getvalue()


# ── 1. MK7 — Buscador por SKU ───────────────────────────────────────────────
def _mk7_positional_progress(emit, total_stores):
    """Adapta el progress_cb POSICIONAL de Falabella/Construmart
    (i, total, store, count, rows_so_far) al stream de eventos del desktop."""
    def cb(i, total, store, count, rows_so_far):
        tot = total or total_stores
        emit({"type": "progress", "phase": "zona", "done": max(0, i - 1), "total": tot,
              "msg": f"Tienda {i}/{tot}: {(store or {}).get('name', '')}"})
        emit({"type": "count", "rows": rows_so_far or 0})
    return cb


async def _run_mk7_generic(params, emit, outdir, tag, mod, out_base, label):
    """MK7 para Falabella/Construmart: mismo contrato de engine
    (read_input / search_skus(metas, stores) / write_output(rows, path) / ALL_STORES)."""
    stores = [s for s in mod.ALL_STORES if s["id"] in set(params["store_ids"])]
    if not stores:
        raise ValueError("No seleccionaste ninguna tienda.")
    df, desc_col, sku_col, easy_col = mod.read_input(params["input_path"])
    has_easy, has_desc = easy_col in df.columns, desc_col in df.columns
    metas, seen = [], set()
    for _, r in df.iterrows():
        sku = str(r[sku_col]).strip()
        if not sku or sku in seen:
            continue
        seen.add(sku)
        metas.append({"sku": sku,
                      "easy": str(r[easy_col]).strip() if has_easy else "",
                      "desc": str(r[desc_col]).strip() if has_desc else ""})
    if not metas:
        raise ValueError("El archivo no tiene SKUs válidos.")
    emit({"type": "info", "msg": f"{len(metas)} SKUs · {len(stores)} tienda(s) · {label}"})
    rows = await mod.search_skus(
        metas, stores, screenshot=bool(params.get("screenshots")), headless=True,
        progress_cb=_mk7_positional_progress(emit, len(stores)))
    if not rows:
        raise RuntimeError(f"No se encontró ningún SKU en {label} para las tiendas elegidas.")
    out = outdir / _outname(out_base, tag)
    emit({"type": "count", "rows": len(rows)})
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(rows)} filas)…"})
    mod.write_output(rows, str(out))
    return out


async def run_mk7(params, emit, outdir: Path, tag: str = ""):
    """params: {retailer, input_path, store_ids, screenshots}. Devuelve la ruta del Excel."""
    retailer = params.get("retailer", "sodimac")
    if retailer == "falabella":
        from engines import falabella_engine as _fe
        return await _run_mk7_generic(params, emit, outdir, tag, _fe, "MK7_Falabella", "Falabella")
    if retailer == "construmart":
        from engines import construmart_engine as _ce
        return await _run_mk7_generic(params, emit, outdir, tag, _ce, "MK7_Construmart", "Construmart")
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
    shots = _shots_dir(outdir, tag) if params.get("screenshots") else None
    matches = await se.search_skus_mk6(
        skus, stores, headless=True, screenshot_dir=(str(shots) if shots else None),
        progress_cb=_zone_progress(emit, len(stores), {"zone": 0}))

    if not matches:
        raise RuntimeError("No se encontró ningún SKU en las tiendas seleccionadas.")

    out = outdir / _outname("MK7_Sodimac", tag)
    emit({"type": "count", "rows": len(matches)})
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(matches)} filas)…"})
    se.write_output(df, desc_col, sku_col, easy_col, matches, str(out), stores=stores)
    return out


# ── 2. Maestra Sección ──────────────────────────────────────────────────────
class _NullProg:
    """Los engines esperan un objeto de progreso estilo rich; acá no aplica."""
    def update(self, *a, **k): pass
    def advance(self, *a, **k): pass


async def discover_sections_desktop(emit, include_landing=True, retailer="sodimac"):
    """Descubre el árbol de secciones (abre el navegador una vez) para el retailer.

    `include_landing=False` para Ferni: su motor deduplica sólo DENTRO de cada
    subcategoría, así que las entradas "Todo X" (roll-up) le duplicarían filas.
    Falabella/Construmart no aceptan include_landing (descubridor propio).
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    emit({"type": "info", "msg": "Abriendo navegador y descubriendo secciones…"})
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT,
                                      viewport={"width": 1280, "height": 900})
            pg = await ctx.new_page()
            if retailer == "falabella":
                from engines import maestra_falabella as m
                tree = await m.discover_sections(pg)
            elif retailer == "construmart":
                from engines import maestra_construmart as m
                tree = await m.discover_sections(pg)
            else:
                from engines import maestra_sodimac as m
                tree = await m.discover_sections(pg, include_landing=include_landing)
        finally:
            await b.close()
    # subcats pueden ser 2- o 3-tuplas (Falabella) → tomamos nombre y URL.
    return [{"section": sec,
             "subcats": [{"name": s[0], "url": s[1]} for s in subs]}
            for sec, subs in tree]


def stores_for_retailer(retailer):
    """Lista estática de tiendas (Sodimac/Falabella = 42 Easy). Construmart es
    dinámico → discover_stores_desktop (async)."""
    if retailer == "falabella":
        from engines import maestra_falabella as m
    else:
        from engines import maestra_sodimac as m
    return [{"id": s["id"], "name": s["name"], "region": s["region"],
             "comuna": s.get("comuna", "")} for s in m.ALL_STORES]


async def discover_stores_desktop(retailer="construmart"):
    """Descubre las tiendas de Construmart (popup del sitio). Abre el navegador."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_construmart as mc
    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
            pg = await ctx.new_page()
            stores = await mc.discover_stores(pg)
        finally:
            await b.close()
    return [{"id": s["id"], "name": s["name"], "region": s.get("region", ""),
             "comuna": s.get("comuna", "")} for s in stores]


async def run_seccion(params, emit, outdir: Path, tag: str = ""):
    """params: {retailer, section, subcats:[{name,url}], store_ids, ...}."""
    retailer = params.get("retailer", "sodimac")
    if retailer == "falabella":
        return await _run_seccion_falabella(params, emit, outdir, tag)
    if retailer == "construmart":
        return await _run_seccion_construmart(params, emit, outdir, tag)
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
    # PARALLEL-SAFE: dir por-job pasado como parámetro a scrape_subcat, NO por la
    # global ms.SCREENSHOT_DIR (que 2 jobs de Sección se pisarían).
    shot_dir = _shots_dir(outdir, tag) if shots else None

    all_rows = []
    total_units = len(stores) * len(subcats)
    unit = 0
    prog = _NullProg()

    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT,
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
                        auto_breadcrumb=(section_name == "Custom"),
                        screenshot_dir=shot_dir)
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
    out = outdir / _outname(f"Seccion_{_safe(section_name)}", tag)
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(all_rows)} filas)…"})
    ms.write_excel(all_rows, str(out), with_images=shots)
    return out


# ── 2b. Maestra Falabella / Construmart ─────────────────────────────────────
async def _run_seccion_falabella(params, emit, outdir, tag=""):
    """Igual a Sodimac pero por ZONA (region/comuna) con maestra_falabella."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_falabella as mf

    stores = [s for s in mf.ALL_STORES if s["id"] in set(params["store_ids"])]
    subcats = [(s["name"], s["url"]) for s in params["subcats"]]
    if not stores or not subcats:
        raise ValueError("Falta seleccionar tienda(s) o subcategoría(s).")
    section_name = params.get("section") or "Sección"
    only_fa = not params.get("include_non_sodimac")  # "solo Falabella" (mismo toggle)
    shots = params.get("screenshots", False)
    all_rows, total_units, unit, prog = [], len(stores) * len(subcats), 0, _NullProg()

    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT,
                                      viewport={"width": 1280, "height": 900}, color_scheme="light")
            page = await ctx.new_page()
            for store in stores:
                emit({"type": "info", "msg": f"Fijando zona: {store['name']}…"})
                ok = await mf.set_zone_with_retry(page, store["region"], store["comuna"])
                if not ok:
                    emit({"type": "warn", "msg": f"No se pudo fijar zona en {store['name']}, se salta."})
                    unit += len(subcats)
                    continue
                seen = {r["SKU"] for r in all_rows if r.get("Tienda") == store["id"] and r.get("SKU")}
                for sc_name, sc_url in subcats:
                    unit += 1
                    emit({"type": "progress", "phase": "subcat", "done": unit,
                          "total": total_units, "msg": f"{store['name']} · {sc_name}"})
                    res = await mf.scrape_subcat(page, section_name, sc_name, sc_url, prog, None,
                                                 download_images=shots, only_falabella=only_fa)
                    for r in res.get("rows", []):
                        sku = r.get("SKU")
                        if not sku or sku in seen:
                            continue
                        seen.add(sku)
                        all_rows.append({"Tienda": store["id"], "Nombre Tienda": store["name"], **r})
                    emit({"type": "count", "rows": len(all_rows)})
        finally:
            await b.close()

    if not all_rows:
        raise RuntimeError("No se obtuvo ninguna fila.")
    out = outdir / _outname(f"Seccion_Falabella_{_safe(section_name)}", tag)
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(all_rows)} filas)…"})
    mf.write_excel(all_rows, str(out), with_images=shots)
    return out


async def _run_seccion_construmart(params, emit, outdir, tag=""):
    """Construmart: por TIENDA (discover_stores dinámico + set_store). Las filas ya
    traen Tienda/Nombre Tienda desde el engine."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    from engines import maestra_construmart as mc

    subcats = [(s["name"], s["url"]) for s in params["subcats"]]
    if not subcats:
        raise ValueError("Falta seleccionar subcategoría(s).")
    section_name = params.get("section") or "Sección"
    shots = params.get("screenshots", False)
    wanted = set(params.get("store_ids") or [])
    all_rows, prog = [], _NullProg()

    async with Stealth().use_async(async_playwright()) as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = await b.new_context(user_agent=USER_AGENT,
                                      viewport={"width": 1280, "height": 900}, color_scheme="light")
            page = await ctx.new_page()
            all_st = await mc.discover_stores(page)
            stores = [s for s in all_st if s["id"] in wanted] or all_st[:1]
            total_units, unit = len(stores) * len(subcats), 0
            for store in stores:
                emit({"type": "info", "msg": f"Fijando tienda: {store['name']}…"})
                ok = await mc.set_store_with_retry(page, store["id"], store.get("region"))
                if not ok:
                    emit({"type": "warn", "msg": f"No se pudo fijar {store['name']}, se salta."})
                    unit += len(subcats)
                    continue
                for sc_name, sc_url in subcats:
                    unit += 1
                    emit({"type": "progress", "phase": "subcat", "done": unit,
                          "total": total_units, "msg": f"{store['name']} · {sc_name}"})
                    res = await mc.scrape_subcat(page, section_name, sc_name, sc_url, store, prog, None,
                                                 download_images=shots)
                    all_rows.extend(res.get("rows", []))
                    emit({"type": "count", "rows": len(all_rows)})
        finally:
            await b.close()

    if not all_rows:
        raise RuntimeError("No se obtuvo ninguna fila.")
    out = outdir / _outname(f"Seccion_Construmart_{_safe(section_name)}", tag)
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(all_rows)} filas)…"})
    mc.write_excel(all_rows, str(out), with_images=shots)
    return out


# ── 3. Fast — Precios por mayor (browserless) ───────────────────────────────
async def run_fast(params, emit, outdir: Path, tag: str = ""):
    """params: {store_ids, sections:[str]|None, url:str|None, wholesale_only, _workers}."""
    from engines import mayoristas_fast as mf
    from engines import maestra_sodimac as ms

    stores = [s for s in ms.ALL_STORES if s["id"] in set(params["store_ids"])]
    if not stores:
        raise ValueError("No seleccionaste ninguna tienda.")
    # _workers lo fija el server: presupuesto total repartido entre los Fast activos.
    workers = int(params.get("_workers") or FAST_WORKERS)
    wholesale_only = params.get("wholesale_only", True)
    url_scope = (params.get("url") or "").strip()
    sections = params.get("sections") or None

    all_rows, report = [], []
    prog = {"rows": 0}  # contador acumulado en vivo (Fast barre 1 tienda ~9 min)
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
            # filas EN VIVO: acumula lo conservado por subcat (antes el count solo
            # salía al terminar la tienda entera → ~9 min en 0).
            prog["rows"] += kept
            emit({"type": "count", "rows": prog["rows"]})

        rows = await asyncio.to_thread(
            mf.scrape_all_wholesale, cookie, tree, store,
            wholesale_only=wholesale_only, only_sodimac=True,
            subcat_cb=subcat_cb, workers=workers, report=report)
        all_rows.extend(rows)
        prog["rows"] = len(all_rows)  # reconcilia con el total real de la tienda
        emit({"type": "count", "rows": len(all_rows)})

    if report:
        emit({"type": "warn",
              "msg": f"{len(report)} categoría(s) no se pudieron leer completas "
                     f"(error de red persistente)."})
    if not all_rows:
        raise RuntimeError("No se obtuvo ninguna fila.")
    kind = "mayoristas" if wholesale_only else "catalogo"
    out = outdir / _outname(f"Fast_{kind}", tag)
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
            # contador de filas EN VIVO: antes MK7/Ferni SKU mostraban 0 todo el
            # rato (solo emitían progreso, nunca 'count') → parecía que no capturaba.
            state["rows"] = state.get("rows", 0) + ev.get("found_in_batch", 0)
            emit({"type": "count", "rows": state["rows"]})
        elif e == "zone_end" and ev.get("zone_failed"):
            emit({"type": "warn", "msg": f"No se pudo fijar zona en {ev['store']['name']}"})
    return cb


async def run_ferni_sku(params, emit, outdir: Path, tag: str = ""):
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
    shot_dir = _shots_dir(outdir, tag) if shots else None

    matches = await fs.search_doors(
        skus, stores, headless=True,
        screenshot_dir=(str(shot_dir) if shot_dir else None),
        progress_cb=_zone_progress(emit, len(stores), {"zone": 0}))
    if not matches:
        raise RuntimeError("No se encontró ninguna puerta en las tiendas seleccionadas.")

    out = outdir / _outname("Ferni_SKU", tag)
    emit({"type": "count", "rows": len(matches)})
    emit({"type": "info", "msg": f"Escribiendo Excel ({len(matches)} filas)…"})
    fs.write_output(df, desc_col, sku_col, easy_col, matches, str(out),
                    stores=stores, embed_images=shots)
    return out


# ── 5. Ferni Sección — puertas y más, por categoría ─────────────────────────
async def run_ferni_seccion(params, emit, outdir: Path, tag: str = ""):
    """params: {section, subcats:[{name,url}], store_ids, screenshots}."""
    from engines import ferni_maestra_sodimac as fm

    from engines import maestra_sodimac as ms
    stores = [s for s in ms.ALL_STORES if s["id"] in set(params["store_ids"])]
    section_name = params.get("section") or "Sección"
    subcats = [(section_name, s["name"], s["url"]) for s in params["subcats"]]
    if not stores or not subcats:
        raise ValueError("Falta seleccionar tienda(s) o subcategoría(s).")

    shots = params.get("screenshots", False)
    shot_dir = _shots_dir(outdir, tag) if shots else None

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
    out = outdir / _outname(f"Ferni_Seccion_{_safe(section_name)}", tag)
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

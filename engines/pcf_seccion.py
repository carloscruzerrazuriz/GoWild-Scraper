# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — Maestra Sección.

Recorre las categorías del catálogo de pcfactory.cl y devuelve una tabla de
productos con precios. Extracción 100% JSON desde la API pública (ver pcf_base):

  - discover_sections(): construye el árbol desde el endpoint `menu`.
  - scrape_section():     pagina el endpoint de productos por cada categoría
                          elegida y arma las rows del Excel.

El backend hace roll-up por id de categoría: pasar el id de un nodo (familia,
subcategoría o hoja) devuelve TODOS los productos de sus descendientes. Por eso
el selector ofrece familias y sus subcategorías directas, y al elegir una se
scrapea el subárbol completo bajo ese id.
"""
from __future__ import annotations

from engines import pcf_base as base

RETAILER_NAME = "PCFactory"


def discover_sections(progress_cb=None):
    """Devuelve [(familia_nombre, [(subcat_nombre, subcat_id), ...]), ...].

    Cada familia top-level del menú con sus subcategorías directas. El `id` de
    cada subcategoría es lo que se pasa a `scrape_section` (el backend expande
    sus descendientes). Si una familia no tiene hijos, se ofrece ella misma.

    `progress_cb` recibe dicts de evento (mismo patrón que el resto del proyecto):
    {"event":"discover", "phase":"load"}.
    """
    if progress_cb:
        progress_cb({"event": "discover", "phase": "load"})
    menu = base.http_json(base.MENU_URL)
    secciones = []
    for fam in menu:
        nombre = fam.get("nombre") or ""
        hijos = fam.get("childCategories") or []
        subcats = [(h.get("nombre") or "", h.get("id")) for h in hijos if h.get("id")]
        if not subcats:
            # Familia sin hijos: ofrecerla a sí misma como única subcategoría.
            if fam.get("id"):
                subcats = [(nombre, fam.get("id"))]
        secciones.append((nombre, subcats))
    return secciones


def _scrape_one(cat_id, *, seccion, subcat, idx, total, on_row, progress_cb, limit):
    """Pagina todos los productos bajo `cat_id`. Devuelve la lista de rows."""
    rows = []
    page = 0
    total_pages = 1
    while page < total_pages:
        url = (f"{base.QUERY_URL}?page={page}&size={base.PAGE_SIZE}"
               f"&categorias={cat_id}")
        data = base.http_json(url)
        content = (data or {}).get("content") or {}
        items = content.get("items") or []
        pageable = content.get("pageable") or {}
        total_pages = pageable.get("totalPages") or 1
        for it in items:
            row = base.make_row(it, seccion=seccion, subcat=subcat)
            rows.append(row)
            if on_row:
                on_row(row)
            if limit and len(rows) >= limit:
                return rows
        if progress_cb:
            progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "page": page + 1,
                         "n_rows": len(rows)})
        page += 1
    return rows


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """Scrapea las categorías seleccionadas.

    `subcats`: lista de tuplas (subcat_nombre, subcat_id) — o ((seccion, subcat),
    id) si el launcher quiere fijar la columna Sección. Acepta ambas formas.

    `on_row(row)`     : callback por cada producto (UI en vivo / checkpoint).
    `progress_cb(ev)` : callback con dicts de evento (patrón del proyecto):
                        subcat_start / subcat_page / subcat_done / complete.
    `limit`           : corta tras N filas totales (para pruebas).
    `zone`            : ignorado (PCFactory tiene precio nacional, sin zona); se
                        acepta por compatibilidad con el contrato del launcher.

    Devuelve la lista completa de rows.
    """
    all_rows = []
    total = len(subcats)
    for i, entry in enumerate(subcats):
        label, cat_id = entry
        if isinstance(label, (tuple, list)) and len(label) == 2:
            seccion, subcat = label
        else:
            seccion, subcat = "", label
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": i + 1, "total": total})
        remaining = (limit - len(all_rows)) if limit else None
        if limit and remaining <= 0:
            break
        rows = _scrape_one(cat_id, seccion=seccion, subcat=subcat, idx=i + 1,
                           total=total, on_row=on_row, progress_cb=progress_cb,
                           limit=remaining)
        all_rows.extend(rows)
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": i + 1, "total": total, "n_rows": len(rows)})
    if progress_cb:
        progress_cb({"event": "complete", "total": total, "n_rows": len(all_rows)})
    return all_rows


def write_excel(rows, path, *, with_images=False):
    """Escribe el Excel (delegado a pcf_base con las columnas de Sección)."""
    base.write_excel(rows, path, sheet_name="Data", with_images=with_images)

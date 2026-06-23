# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Ferrobal (plataforma WooCommerce / WordPress).

Extracción por la Store API pública de WooCommerce (sin auth, sin DOM):
  - Categorías: /wp-json/wc/store/v1/products/categories
  - Productos:  /wp-json/wc/store/v1/products?category={id}&per_page=100&page=N

Precios en `prices`: `price` (vigente = internet) y `regular_price` (normal),
en unidades menores → se dividen por 10**currency_minor_unit.
WooCommerce no tiene jerarquía profunda fija; aquí cada categoría Woo se trata
como una "subcategoría", agrupada por su categoría padre como "sección".
"""
from __future__ import annotations

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Ferrobal"
USES_BROWSER = False
ZONE_NOTE = ("Ferrobal (WooCommerce) tiene **precio único**: Woo no maneja price-list "
             "por zona; la comuna sólo aplica al despacho en el checkout. Por eso no "
             "hay selector de zona. Nota: el catálogo Woo no expone la marca del "
             "producto en el listado → la columna Marca puede salir vacía.")
BASE = "https://ferrobal.cl/wp-json/wc/store/v1"
SITE = "https://ferrobal.cl"

_PER_PAGE = 100
_MAX_PAGES = 50  # tope de seguridad por categoría


def _discover_sections():
    """[(sección, [(subcategoría, category_id), ...]), ...] desde las categorías Woo.

    Agrupa las categorías por su `parent`: las hijas cuelgan de su padre; las
    categorías raíz (parent=0) con productos quedan como su propia sección.
    """
    cats = []
    page = 1
    while page <= 10:
        batch = _b.http_json(f"{BASE}/products/categories?per_page=100&page={page}")
        if not batch:
            break
        cats.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    by_id = {c["id"]: c for c in cats}
    children = {}
    roots = []
    for c in cats:
        if c.get("count", 0) <= 0:
            continue
        parent = c.get("parent", 0)
        if parent and parent in by_id:
            children.setdefault(parent, []).append(c)
        else:
            roots.append(c)

    out = []
    for root in sorted(roots, key=lambda c: c["name"]):
        kids = children.get(root["id"], [])
        if kids:
            subs = [(f"{k['name']} ({k['count']})", str(k["id"]))
                    for k in sorted(kids, key=lambda c: c["name"])]
            # incluir también la raíz misma para no perder sus productos directos
            subs.insert(0, (f"{root['name']} — todo ({root['count']})", str(root["id"])))
        else:
            subs = [(f"{root['name']} ({root['count']})", str(root["id"]))]
        out.append((root["name"], subs))
    return out


def _money(prices, key):
    try:
        minor = int(prices.get("currency_minor_unit", 0) or 0)
        div = 10 ** minor if minor else 1
        raw = prices.get(key)
        return int(raw) / div if raw not in (None, "") else ""
    except (TypeError, ValueError):
        return ""


def _extract(p, seccion, subcat):
    prices = p.get("prices") or {}
    internet = _money(prices, "price")
    normal = _money(prices, "regular_price")
    imgs = p.get("images") or []
    img = (imgs[0].get("thumbnail") or imgs[0].get("src")) if imgs else ""
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca="", sku=p.get("sku", ""),
        descripcion=p.get("name", ""),
        precio_normal=normal, precio_internet=internet,
        url=p.get("permalink", ""), img=img,
    )


def discover_sections(progress_cb=None):  # noqa: ARG001 (progress_cb por uniformidad)
    return _discover_sections()


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, category_id), ...]. Devuelve filas.

    `zone` se ignora: Ferrobal (WooCommerce) tiene precio único (sin price-list
    por zona); la comuna sólo aplica al despacho en el checkout.
    """
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, cat_id) in enumerate(subcats, 1):
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total})
        page = 1
        seen = 0
        while page <= _MAX_PAGES:
            url = f"{BASE}/products?category={cat_id}&per_page={_PER_PAGE}&page={page}"
            try:
                prods = _b.http_json(url)
            except Exception:
                break
            if not prods:
                break
            for p in prods:
                r = _extract(p, seccion, subcat)
                rows.append(r); seen += 1
                if on_row:
                    on_row(r)
                if limit and seen >= limit:
                    break
            if progress_cb:
                progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                             "page": page, "n_rows": len(rows)})
            if (limit and seen >= limit) or len(prods) < _PER_PAGE:
                break
            page += 1
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

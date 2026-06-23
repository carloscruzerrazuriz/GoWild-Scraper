# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · PuntoMaestro (plataforma VTEX).

Extracción 100% por API pública de catálogo VTEX (sin DOM, sin navegador):
  - Árbol de categorías: /api/catalog_system/pub/category/tree/3
  - Productos por categoría: /api/catalog_system/pub/products/search/?fq=C:/{id}/

Precio: items[].sellers[].commertialOffer (Price = internet, ListPrice = normal).
VTEX limita la ventana _from/_to a 50 por request y ~2500 productos por query.
"""
from __future__ import annotations

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "PuntoMaestro"
USES_BROWSER = False
ZONE_NOTE = ("PuntoMaestro (VTEX) tiene **precio único nacional**: se verificó que la "
             "región VTEX devuelve el mismo precio para RM/Antofagasta/Punta Arenas "
             "(la ubicación sólo afecta despacho y stock, no el precio). Por eso no hay "
             "selector de zona — sería un control que no cambia nada.")
BASE = "https://www.puntomaestro.cl"

_PAGE = 50          # máximo permitido por VTEX en una ventana _from/_to
_MAX_PER_CAT = 2500  # tope duro de la API de búsqueda VTEX


def _discover_sections():
    """[(sección, [(subcategoría, cat_path), ...]), ...] desde el árbol VTEX.

    `cat_path` es la RUTA completa de categoría (ej. "1/10") porque el filtro
    VTEX `fq=C:/dept/sub/` exige la jerarquía completa, no solo el id del hijo.
    """
    tree = _b.http_json(f"{BASE}/api/catalog_system/pub/category/tree/3")
    out = []
    for dept in tree:
        did = dept["id"]
        subs = [(c["name"], f"{did}/{c['id']}") for c in dept.get("children", [])]
        # Si un departamento no tiene hijos, se ofrece a sí mismo como única subcat.
        if not subs:
            subs = [(dept["name"], str(did))]
        out.append((dept["name"], subs))
    return out


def _extract(p, seccion, subcat):
    it = (p.get("items") or [{}])[0]
    seller = (it.get("sellers") or [{}])[0]
    offer = seller.get("commertialOffer") or {}
    price = offer.get("Price")
    listp = offer.get("ListPrice")
    sku = p.get("productReference") or it.get("itemId") or p.get("productId", "")
    link = p.get("linkText", "")
    img = (it.get("images") or [{}])[0].get("imageUrl", "")
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca=p.get("brand", ""), sku=sku,
        descripcion=p.get("productName", ""),
        precio_normal=listp, precio_internet=price,
        url=f"{BASE}/{link}/p" if link else "", img=img,
    )


def discover_sections(progress_cb=None):  # noqa: ARG001 (progress_cb por uniformidad)
    return _discover_sections()


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, category_id), ...]. Devuelve filas.

    `zone` se ignora: PuntoMaestro tiene precio único nacional (verificado: la
    región VTEX no cambia el precio del catálogo, solo despacho/stock).
    """
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, cat_id) in enumerate(subcats, 1):
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total})
        frm = 0
        seen = 0
        while frm < _MAX_PER_CAT:
            to = frm + _PAGE - 1
            url = (f"{BASE}/api/catalog_system/pub/products/search/"
                   f"?fq=C:/{cat_id}/&_from={frm}&_to={to}")
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
                             "page": frm // _PAGE + 1, "n_rows": len(rows)})
            if (limit and seen >= limit) or len(prods) < _PAGE:
                break
            frm += _PAGE
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

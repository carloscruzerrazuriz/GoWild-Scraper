# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Oviedo / Ferretería Oviedo (PHP custom + Apache).

Sin API pública: catálogo server-rendered, se extrae del DOM con HTML plano
(urllib + BeautifulSoup):
  - Categorías: `categorias/{id}/{slug}` (sección). Subcategorías:
    `subcategorias/{subid}/{slug}` (el subid empieza con el id de su categoría
    padre → así se agrupan). Ambas listan productos.
  - Productos (PLP): cards `.grilla`; paginación añadiendo `/0/0/0/0/16/pagina-N`
    a la ruta.

Card: `.nombreGrilla` = nombre, `.skuGrilla` = "(SKU)", `.antes2` = "Antes $X"
(normal), `.conDescuento` = "$Y IVA Inc." (internet); si no hay descuento,
`.valorGrilla` trae el precio único. Precio único de sitio → sin selector de zona.
"""
from __future__ import annotations

import re

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Oviedo"
USES_BROWSER = False
BASE = "https://www.oviedo.cl"
_PER_PAGE = 16
_MAX_PAGES = 120


def _soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _norm(href):
    """Ruta relativa limpia (sin dominio, sin barra inicial, sin query)."""
    return re.sub(r"https?://[^/]+", "", href or "").split("?")[0].strip("/")


def discover_sections(progress_cb=None):
    """[(categoría, [(subcategoría, ref), ...]), ...] desde la home.

    Sección = categoría. Subcategorías = las `subcategorias/{id}` cuyo id empieza
    con el id de la categoría, más una entrada "▸ Toda la categoría" que recorre
    la categoría completa (paginada).
    """
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 0, "total": 1})
    html = _b.http_text(f"{BASE}/")
    soup = _soup(html)
    cats = {}   # catid -> (name, ref)
    subs = {}   # subid -> (name, ref)
    for a in soup.find_all("a", href=True):
        p = _norm(a.get("href")); t = a.get_text(strip=True)
        if not t:
            continue
        m = re.match(r"^categorias/(\d+)/", p)
        if m:
            cats.setdefault(m.group(1), (t, p)); continue
        m = re.match(r"^subcategorias/(\d+)/", p)
        if m:
            subs.setdefault(m.group(1), (t, p))
    cat_ids = sorted(cats, key=len, reverse=True)   # match más largo primero
    children = {}
    for subid, (sname, sref) in subs.items():
        parent = next((cid for cid in cat_ids if subid.startswith(cid)), None)
        if parent:
            children.setdefault(parent, []).append((sname, sref))
    out = []
    for catid, (cname, cref) in cats.items():
        sub_list = [("▸ Toda la categoría", cref)]
        sub_list += sorted(children.get(catid, []), key=lambda x: x[0])
        out.append((cname, sub_list))
    out.sort(key=lambda x: x[0])
    if progress_cb:
        progress_cb({"event": "discover", "phase": "done", "done": 1, "total": 1})
    return out


def _money(txt):
    m = re.search(r"\$\s?([\d\.]+)", txt or "")
    if not m:
        return ""
    try:
        return float(m.group(1).replace(".", ""))
    except ValueError:
        return ""


def _txt(card, sel):
    el = card.select_one(sel)
    return el.get_text(" ", strip=True) if el else ""


def _extract(card, seccion, subcat):
    name = _txt(card, ".nombreGrilla")
    sku = re.sub(r"[()]", "", _txt(card, ".skuGrilla")).strip()
    a = card.select_one("a[href*='ficha/']") or card.select_one(".nombreGrilla")
    url = a.get("href") if a and a.get("href") else ""
    if url and not url.startswith("http"):
        url = f"{BASE}/{url.lstrip('/')}"
    normal = _money(_txt(card, ".antes2"))
    internet = _money(_txt(card, ".conDescuento"))
    if internet == "":
        internet = _money(_txt(card, ".valorGrilla"))
    if normal == "":
        normal = internet
    img_el = card.select_one("img.imgGrilla, img")
    img = ""
    if img_el:
        img = img_el.get("src") or img_el.get("data-src") or img_el.get("data-original") or ""
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca="", sku=sku, descripcion=name,
        precio_normal=normal, precio_internet=internet,
        url=url, img=img,
    )


def _page_url(ref, page):
    if page <= 1:
        return f"{BASE}/{ref}"
    return f"{BASE}/{ref}/0/0/0/0/{_PER_PAGE}/pagina-{page}"


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, ref), ...]. `zone` se ignora (precio único)."""
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, ref) in enumerate(subcats, 1):
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total})
        page = 1
        seen = 0
        seen_skus = set()
        while page <= _MAX_PAGES:
            try:
                html = _b.http_text(_page_url(ref, page))
            except Exception:
                break
            soup = _soup(html)
            cards = soup.select(".grilla")
            if not cards:
                break
            added = 0
            for c in cards:
                r = _extract(c, seccion, subcat)
                key = r["SKU"] or r["URL"]
                if key in seen_skus:
                    continue
                seen_skus.add(key)
                rows.append(r); seen += 1; added += 1
                if on_row:
                    on_row(r)
                if limit and seen >= limit:
                    break
            if progress_cb:
                progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                             "page": page, "n_rows": len(rows)})
            if (limit and seen >= limit) or len(cards) < _PER_PAGE or added == 0:
                break
            page += 1
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

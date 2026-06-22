# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Construplaza (plataforma Magento, tienda Matucana 27).

Magento renderiza el catálogo server-side (no hay API JSON pública limpia: el
GraphQL exige header Store y da 500), así que se extrae del DOM con HTML plano
(urllib + BeautifulSoup), sin navegador:
  - Árbol de categorías: del menú `nav.navigation` de la home (links .html
    jerárquicos dept/subcat.html).
  - Productos por categoría (PLP): `li.product-item`, precios en
    `[data-price-amount]` (especial = internet, normal = tachado). Paginación `?p=N`.

Construplaza es **multistore Magento**: la "tienda" se elige por la URL/cookie.
Acá se usa la tienda por defecto (Matucana 27, la que pidió Mauro); el precio de
catálogo es el de esa tienda. No hay selector de zona (un solo store-view).
"""
from __future__ import annotations

import re

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Construplaza"
USES_BROWSER = False
BASE = "https://www.construplaza.cl"

_MAX_PAGES = 60  # tope de seguridad por subcategoría


def _soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _path(href):
    return re.sub(r"https?://[^/]+", "", href or "").split("?")[0].strip("/")


def discover_sections(progress_cb=None):
    """[(sección, [(subcategoría, cat_path), ...]), ...] desde el menú Magento.

    Sección = departamento (1er segmento). Subcategorías = categorías de 2º nivel
    (`dept/sub.html`); las de 3er nivel hacen roll-up en su padre, así que con el
    2º nivel basta para cubrir el catálogo sin duplicar.
    """
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 0, "total": 1})
    html = _b.http_text(f"{BASE}/")
    soup = _soup(html)
    nav = soup.select_one("nav.navigation") or soup
    dept_name = {}     # slug -> nombre legible
    subs = {}          # dept_slug -> {path: nombre}
    for a in nav.find_all("a", href=re.compile(r"\.html(?:$|\?)")):
        p = _path(a.get("href"))
        if not p.endswith(".html"):
            continue
        parts = p[:-5].split("/")  # sin .html
        txt = a.get_text(strip=True)
        if len(parts) == 1:
            if txt and txt.lower() != "ver todo":
                dept_name.setdefault(parts[0], txt)
        elif len(parts) == 2:
            if txt and txt.lower() != "ver todo":
                subs.setdefault(parts[0], {})[p] = txt
    out = []
    for dept_slug, sub_map in subs.items():
        name = dept_name.get(dept_slug) or dept_slug.replace("-", " ").title()
        sub_list = sorted(((nm, path) for path, nm in sub_map.items()),
                          key=lambda x: x[0])
        if sub_list:
            out.append((name, sub_list))
    out.sort(key=lambda x: x[0])
    if progress_cb:
        progress_cb({"event": "discover", "phase": "done", "done": 1, "total": 1})
    return out


def _amounts(item):
    """Lista de precios numéricos (`data-price-amount`) presentes en la card."""
    vals = []
    for el in item.select("[data-price-amount]"):
        raw = el.get("data-price-amount")
        try:
            v = float(raw)
            if v > 0:
                vals.append(v)
        except (TypeError, ValueError):
            pass
    return vals


def _extract(item, seccion, subcat):
    link = item.select_one("a.product-item-link") or item.select_one(".product-item-name a")
    name = link.get_text(strip=True) if link else ""
    url = link.get("href") if link else ""
    amts = _amounts(item)
    if len(set(amts)) >= 2:
        internet, normal = min(amts), max(amts)
    elif amts:
        internet = normal = amts[0]
    else:
        internet = normal = ""
    # SKU: del slug del producto (construplaza-XXccc.html) o el data-product-id.
    sku = ""
    m = re.search(r"/([^/]+)\.html$", url or "")
    if m:
        sku = re.sub(r"^construplaza-", "", m.group(1))
    form = item.select_one("[data-product-id]")
    if not sku and form:
        sku = form.get("data-product-id")
    img_el = item.select_one("img.product-image-photo, img")
    img = ""
    if img_el:
        img = img_el.get("src") or img_el.get("data-src") or ""
    brand_el = item.select_one(".product-item-brand, [class*=brand]")
    brand = brand_el.get_text(strip=True) if brand_el else ""
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca=brand, sku=sku, descripcion=name,
        precio_normal=normal, precio_internet=internet,
        url=url, img=img,
    )


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, cat_path), ...]. Devuelve filas.

    `zone` se ignora: la tienda (store-view) es fija (Matucana 27).
    """
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, cat_path) in enumerate(subcats, 1):
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total})
        page = 1
        seen = 0
        while page <= _MAX_PAGES:
            url = f"{BASE}/{cat_path}" + (f"?p={page}" if page > 1 else "")
            try:
                html = _b.http_text(url)
            except Exception:
                break
            soup = _soup(html)
            items = soup.select("li.product-item")
            if not items:
                break
            for it in items:
                r = _extract(it, seccion, subcat)
                rows.append(r); seen += 1
                if on_row:
                    on_row(r)
                if limit and seen >= limit:
                    break
            if progress_cb:
                progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                             "page": page, "n_rows": len(rows)})
            if limit and seen >= limit:
                break
            # ¿hay página siguiente? Magento muestra link a ?p=page+1 en .pages
            nxt = soup.select_one(f'.pages a[href*="p={page+1}"], a.action.next')
            if not nxt:
                break
            page += 1
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · DVP (plataforma Salesforce Commerce Cloud / Demandware).

SFCC renderiza la grilla server-side (OCAPI requiere client_id → no es vía
pública), así que se extrae del DOM con HTML plano (urllib + BeautifulSoup):
  - Árbol de categorías: del menú de la home (slugs dept / dept/subcat).
  - Productos por categoría (PLP): `.product-tile`. La primera página viene en la
    URL del slug; el resto se pagina por el endpoint estándar de SFCC
    `Search-UpdateGrid?cgid={cgid}&start=N&sz=M` (devuelve fragmento de tiles).

Precio: `.sales .value[content]` (= internet) y `.strike-through .value[content]`
(= normal/tachado). SKU en `.product-id` ("SKU:xxxx") o el `data-pid` del tile.
La zona/sucursal SFCC no cambia el precio de catálogo (precio único de sitio).
"""
from __future__ import annotations

import re

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "DVP"
USES_BROWSER = False
ZONE_NOTE = ("DVP (Salesforce Commerce) sirve **precio único de sitio** en su catálogo; "
             "la sucursal/región sólo afecta despacho. Por eso no hay selector de zona. "
             "Nota: los tiles del listado no exponen la marca → la columna Marca puede "
             "salir vacía.")
BASE = "https://www.dvp.cl"
_GRID = (BASE + "/on/demandware.store/Sites-dvp-chile-Site/es_CL/"
         "Search-UpdateGrid?cgid={cgid}&start={start}&sz={sz}")
_SZ = 24
_MAX_PRODUCTS = 5000  # tope de seguridad por subcategoría

_UTIL = {"login", "sucursales", "mi-carrito", "carro", "cotizador", "cuenta",
         "account", "wishlist", "contacto", "blog", "page-video", "checkout"}
# Slugs de contenido SFCC (no categorías): ids alfanuméricos random tipo "gRUFhz...".
_CONTENT_ID = re.compile(r"^[A-Za-z0-9_-]{12,}$")


def _is_content_slug(slug):
    """True si el slug parece un content-asset id SFCC (no una categoría real)."""
    if "/" in slug or "-" in slug:
        return False
    return bool(_CONTENT_ID.match(slug)) and any(c.isdigit() for c in slug) \
        and any(c.isupper() for c in slug)


def _soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _path(href):
    return re.sub(r"https?://[^/]+", "", href or "").split("?")[0].strip("/")


def discover_sections(progress_cb=None):
    """[(sección, [(subcategoría, slug_path), ...]), ...] desde el menú SFCC.

    Sección = slug de nivel 1; subcategorías = slugs de nivel 2. El slug es la
    ref que el scrape resuelve a su `cgid` leyendo la 1ª página de la categoría.
    """
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 0, "total": 1})
    html = _b.http_text(f"{BASE}/")
    soup = _soup(html)
    depts = {}        # dept_slug -> {"name": str, "subs": {path: name}}
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        t = a.get_text(strip=True)
        p = _path(href)
        if not p or not t or "." in p or "#" in href or "tel:" in href:
            continue
        parts = p.split("/")
        if parts[0] in _UTIL or _is_content_slug(parts[0]):
            continue
        if len(parts) == 1:
            depts.setdefault(parts[0], {"name": None, "subs": {}})
            depts[parts[0]]["name"] = depts[parts[0]]["name"] or t
        elif len(parts) == 2:
            d = depts.setdefault(parts[0], {"name": None, "subs": {}})
            d["subs"][p] = t
    out = []
    for slug, d in depts.items():
        # Solo departamentos reales: los que tienen subcategorías de nivel 2.
        # (Descarta controles de carrusel/accesibilidad sueltos: Previous, Skip…)
        if not d["subs"]:
            continue
        name = d["name"] or slug.replace("-", " ").title()
        subs = sorted(((nm, path) for path, nm in d["subs"].items()), key=lambda x: x[0])
        out.append((name, subs))
    out.sort(key=lambda x: x[0])
    if progress_cb:
        progress_cb({"event": "discover", "phase": "done", "done": 1, "total": 1})
    return out


def _price(tile, sel):
    el = tile.select_one(sel)
    if not el:
        return ""
    if el.get("content"):
        try:
            return float(el.get("content"))
        except (TypeError, ValueError):
            pass
    m = re.search(r"[\d\.]{3,}", el.get_text(" ", strip=True))
    if m:
        try:
            return float(m.group(0).replace(".", ""))
        except ValueError:
            pass
    return ""


def _extract(tile, seccion, subcat):
    link = tile.select_one(".pdp-link a.link, .pdp-link a, a.link")
    name = link.get_text(strip=True) if link else ""
    url = link.get("href") if link else ""
    if url and url.startswith("/"):
        url = BASE + url
    internet = _price(tile, ".sales .value")
    normal = _price(tile, ".strike-through .value, .list .value")
    if normal in (None, ""):
        normal = internet
    # SKU
    sku = ""
    pid = tile.select_one("[data-pid]")
    if pid:
        sku = pid.get("data-pid")
    if not sku:
        sid = tile.select_one(".product-id")
        if sid:
            sku = re.sub(r"(?i)^sku:\s*", "", sid.get_text(strip=True))
    img_el = tile.select_one("img.tile-image, img")
    img = ""
    if img_el:
        img = img_el.get("src") or img_el.get("data-src") or ""
        if img and img.startswith("/"):
            img = BASE + img
    brand_el = tile.select_one(".product-brand, [class*=brand]")
    brand = brand_el.get_text(strip=True) if brand_el else ""
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca=brand, sku=sku, descripcion=name,
        precio_normal=normal, precio_internet=internet,
        url=url, img=img,
    )


def _cgid_from(html):
    m = re.search(r"Search-UpdateGrid\?cgid=([^&\"'>]+)", html)
    return m.group(1) if m else None


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, slug_path), ...]. Devuelve filas.

    `zone` se ignora (precio único de sitio en SFCC DVP).
    """
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, slug) in enumerate(subcats, 1):
        if progress_cb:
            progress_cb({"event": "subcat_start", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total})
        seen = 0
        seen_skus = set()
        # 1ª página: la PLP del slug (trae cgid + primeros tiles). La PLP inicial
        # de SFCC suele renderizar un bloque chico (~12); el resto SIEMPRE se pide
        # por Search-UpdateGrid con start=offset hasta que devuelve 0 tiles.
        try:
            html = _b.http_text(f"{BASE}/{slug}")
        except Exception:
            html = ""
        cgid = _cgid_from(html) if html else None
        page = 1
        stop = False
        while html and not stop:
            soup = _soup(html)
            tiles = soup.select(".product-tile")
            if not tiles:
                break
            added = 0
            for t in tiles:
                r = _extract(t, seccion, subcat)
                key = r["SKU"] or r["URL"]
                if key in seen_skus:
                    continue          # el grid puede solapar; dedup defensivo
                seen_skus.add(key)
                rows.append(r); seen += 1; added += 1
                if on_row:
                    on_row(r)
                if limit and seen >= limit:
                    stop = True
                    break
            if progress_cb:
                progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                             "page": page, "n_rows": len(rows)})
            if stop or not cgid or seen >= _MAX_PRODUCTS or added == 0:
                break
            # Siguiente bloque vía Search-UpdateGrid (offset = total acumulado).
            try:
                html = _b.http_text(_GRID.format(cgid=cgid, start=seen, sz=_SZ))
            except Exception:
                break
            page += 1
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

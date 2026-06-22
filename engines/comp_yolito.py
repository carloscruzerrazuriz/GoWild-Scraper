# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Yolito (plataforma ASP.NET / IIS).

Sin API pública: el catálogo es server-rendered, se extrae del DOM con HTML plano
(urllib + BeautifulSoup):
  - Departamentos: del menú de la home (`/Productos/<dept>`).
  - Subcategorías: de la página de cada departamento (`/Productos/<dept>/<sub>`).
  - Productos (PLP): cards `.c-i-prod` (36 por página); paginación `?page=N`.

Card: `h3` = marca, el `<div>` siguiente / `img@alt` = nombre, `<span>$` = precio,
link `/Producto/{sku}`. Precio único (sin price-list por zona) → sin selector de
zona; si una card trae 2 montos se interpreta menor=internet, mayor=normal.
"""
from __future__ import annotations

import re

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Yolito"
USES_BROWSER = False
BASE = "https://www.yolito.cl"
_MAX_PAGES = 80          # tope de seguridad por subcategoría
_PER_PAGE = 36           # cards por página (para detectar última página)


def _soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def _dept_subcats(dept_slug):
    """[(subcat_name, '/Productos/dept/sub'), ...] de la página de un departamento."""
    try:
        html = _b.http_text(f"{BASE}/Productos/{dept_slug}")
    except Exception:
        return []
    soup = _soup(html)
    pref = f"/Productos/{dept_slug}/"
    seen = {}
    for a in soup.find_all("a", href=True):
        h = a.get("href"); t = a.get_text(strip=True)
        if h.startswith(pref) and t:
            ref = h.split("?")[0]
            seen.setdefault(ref, t)
    return sorted(((nm, ref) for ref, nm in seen.items()), key=lambda x: x[0])


def discover_sections(progress_cb=None):
    """[(departamento, [(subcategoría, ref), ...]), ...].

    Departamentos del menú de la home; subcategorías cargadas de cada página de
    departamento (en paralelo para no demorar). Un dept sin subcats se ofrece a
    sí mismo como única subcategoría.
    """
    from concurrent.futures import ThreadPoolExecutor
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 0, "total": 1})
    html = _b.http_text(f"{BASE}/")
    soup = _soup(html)
    depts = {}   # slug -> name
    for a in soup.find_all("a", href=True):
        h = a.get("href"); t = a.get_text(strip=True)
        m = re.match(r"^/Productos/([^/?#]+)/?$", h)
        if m and t:
            depts.setdefault(m.group(1), t)
    items = list(depts.items())
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": 1, "total": len(items) + 1})
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda kv: (kv[1], kv[0], _dept_subcats(kv[0])), items))
    for name, slug, subs in results:
        if not subs:
            subs = [(name, f"/Productos/{slug}")]
        out.append((name, subs))
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


def _extract(card, seccion, subcat):
    a = card.select_one("a[href*='/Producto/']")
    url = a.get("href") if a else ""
    if url and url.startswith("/"):
        url = BASE + url
    sku = ""
    m = re.search(r"/Producto/([^/?#]+)", url)
    if m:
        sku = m.group(1)
    img = card.select_one("img")
    name = (img.get("alt").strip() if img and img.get("alt") else "")
    brand_el = card.select_one("h3")
    brand = brand_el.get_text(strip=True) if brand_el else ""
    if not name:
        # fallback: el div de nombre (sin el h3 de marca)
        det = card.select_one(".c-prod-det")
        if det:
            name = det.get_text(" ", strip=True)
    # precios: todos los $ de la card
    amounts = []
    for sp in card.find_all(["span", "b", "strong", "div"]):
        if sp.find(["span", "div"]):
            continue
        v = _money(sp.get_text(" ", strip=True))
        if v != "":
            amounts.append(v)
    amounts = [v for v in amounts if v > 0]
    if len(set(amounts)) >= 2:
        internet, normal = min(amounts), max(amounts)
    elif amounts:
        internet = normal = amounts[0]
    else:
        internet = normal = ""
    img_url = ""
    if img:
        img_url = img.get("src") or img.get("data-original") or img.get("data-src") or ""
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=seccion, subcat=subcat,
        marca=brand, sku=sku, descripcion=name,
        precio_normal=normal, precio_internet=internet,
        url=url, img=img_url,
    )


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None, zone=None):
    """subcats: [(sección, subcategoría, ref), ...]. Devuelve filas.

    `ref` es la ruta `/Productos/dept[/sub]`. `zone` se ignora (precio único).
    """
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
            url = f"{BASE}{ref}" + (f"?page={page}" if page > 1 else "")
            try:
                html = _b.http_text(url)
            except Exception:
                break
            soup = _soup(html)
            cards = soup.select(".c-i-prod")
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

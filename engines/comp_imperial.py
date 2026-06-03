# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores · Imperial (plataforma Oracle Commerce Cloud).

Extracción por la API REST pública de Oracle Commerce Cloud (sin DOM):
  - Árbol de categorías: /ccstoreui/v1/collections/rootCategory?fields=childCategories...
  - Productos por categoría: /ccstoreui/v1/products?categoryId={repoId}&Nrpp=250&offset=N

Precio (clave): NO viene en el campo top-level `listPrice` (proyecta null), SÍ en
`childSKUs[0].listPrices` / `salePrices` (también en el item-level `listPrices`):
  - `_default_price_book`  = precio por defecto.
  - `z001`..`z015`         = 15 price-books por sucursal/zona → en Imperial la ZONA
                             literalmente cambia el precio. Por defecto usamos
                             `_default_price_book`; ZONE_PRICE_BOOK permite fijar otra.
"""
from __future__ import annotations

from engines import comp_base as _b

write_excel = _b.write_excel    # re-export del contrato uniforme
OUTPUT_COLS = _b.OUTPUT_COLS

RETAILER_NAME = "Imperial"
USES_BROWSER = False
BASE = "https://www.imperial.cl/ccstoreui/v1"
SITE = "https://www.imperial.cl"

# Price-book a usar para el precio. "_default_price_book" o "z001".."z015".
ZONE_PRICE_BOOK = "_default_price_book"

_PAGE = 250
_MAX_OFFSET = 20000


ALL_REF = "__ALL__"  # ref especial: enumerar el catálogo completo (sin precio)
_DISCOVER_PAGES = 60  # tope de páginas (×250) a escanear para armar el árbol


def _slug_name(route):
    """Nombre legible del primer segmento del route (decodifica %XX)."""
    import urllib.parse
    seg = (route or "").strip("/").split("/")[0] if route else ""
    return urllib.parse.unquote(seg).replace("-", " ").title() if seg else "(sin categoría)"


def _dept_of(parent_cat):
    """Sube por fixedParentCategories hasta el departamento (hijo directo de rootCategory)."""
    node = parent_cat
    dept = node.get("repositoryId")
    while node:
        fps = node.get("fixedParentCategories") or []
        if not fps:
            break
        nxt = fps[0]
        if nxt.get("repositoryId") == "rootCategory":
            break
        dept = nxt.get("repositoryId")
        node = nxt
    return dept


def discover_sections(zone_price_book=None):
    """Árbol real de catálogo de Imperial, cosechado del propio catálogo.

    Imperial (Oracle CC) tiene DOS taxonomías: la de navegación (rootCategory,
    sin productos directos, displayName nulos en profundidad) y la de catálogo
    (ids 00030003…, que SÍ devuelven productos con precio al filtrar por
    categoryId). El árbol de catálogo no es enumerable como colección, pero CADA
    producto trae su jerarquía completa en `parentCategories[].fixedParentCategories`
    (hoja → … → departamento → rootCategory). Acá se escanea el catálogo (liviano,
    sin precio) para reconstruir: departamento → categorías-hoja, con su conteo.

    Devuelve [(departamento, [(hoja (n), leaf_category_id), ...]), ...].
    El scrape posterior consulta por categoryId → ahí vienen los precios.
    """
    # {dept_id: {"name":?, "leaves": {leaf_id: {"name":?, "count":int}}}}
    depts = {}
    dept_ids = set()
    offset = 0
    for _ in range(_DISCOVER_PAGES):
        url = f"{BASE}/products?offset={offset}&Nrpp={_PAGE}&totalResults=true"
        try:
            data = _b.http_json(url)
        except Exception:
            break
        items = data.get("items") or []
        if not items:
            break
        for p in items:
            name = _slug_name(p.get("route", ""))
            for pc in (p.get("parentCategories") or []):
                leaf_id = pc.get("repositoryId")
                if not leaf_id:
                    continue
                dept_id = _dept_of(pc) or leaf_id
                dept_ids.add(dept_id)
                d = depts.setdefault(dept_id, {"name": None, "leaves": {}})
                lf = d["leaves"].setdefault(leaf_id, {"name": name, "count": 0})
                lf["count"] += 1
                break  # solo la categoría primaria del producto
        total = data.get("totalResults", 0)
        offset += _PAGE
        if offset >= (total or 0):
            break

    # Resolver el nombre de cada departamento (1 query por depto, ~11 en total).
    for dept_id in dept_ids:
        try:
            r = _b.http_json(f"{BASE}/products?categoryId={dept_id}&offset=0&Nrpp=1")
            nm = (r.get("category") or {}).get("displayName")
            if nm:
                depts[dept_id]["name"] = nm
        except Exception:
            pass

    out = []
    for dept_id, d in depts.items():
        dept_name = d["name"] or f"Departamento {dept_id}"
        subs = [(f"{lf['name']} ({lf['count']})", lid)
                for lid, lf in sorted(d["leaves"].items(), key=lambda kv: kv[1]["name"])]
        if subs:
            out.append((dept_name, subs))
    out.sort(key=lambda x: x[0])
    return out


def _price(p, sku, kind, book):
    """Precio del price-book `book` para `kind` ('listPrices'|'salePrices').

    El precio real vive en el childSKU; el item-level suele traer el dict pero con
    `_default_price_book=None`, así que se prioriza el childSKU y luego el item.
    """
    for src in (sku.get(kind), p.get(kind)):
        if isinstance(src, dict):
            v = src.get(book)
            if v not in (None, ""):
                return v
    return None


def _section_from_route(route):
    """Primer segmento del route como nombre de sección legible (ej. 'Cerraduras Muebles')."""
    seg = (route or "").strip("/").split("/")[0] if route else ""
    return seg.replace("-", " ").title() if seg else "(sin categoría)"


def _extract(p, seccion, subcat, book):
    sku = (p.get("childSKUs") or [{}])[0]
    normal = _price(p, sku, "listPrices", book)
    sale = _price(p, sku, "salePrices", book)
    internet = sale if sale not in (None, "") else normal  # sin oferta → internet = normal
    skuid = sku.get("repositoryId") or p.get("id", "")
    route = p.get("route", "")
    # En modo catálogo la sección sale del route del producto.
    sec = seccion or _section_from_route(route)
    return _b.make_row(
        tienda=RETAILER_NAME, seccion=sec, subcat=subcat or sec,
        marca=p.get("brand", ""), sku=skuid,
        descripcion=p.get("displayName", ""),
        precio_normal=normal, precio_internet=internet,
        url=f"{SITE}{route}" if route else "",
    )


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None,
                   zone_price_book=None):
    """subcats: [(sección, subcategoría, category_repoId), ...]. Devuelve filas."""
    book = zone_price_book or ZONE_PRICE_BOOK
    rows = []
    total = len(subcats)
    for idx, (seccion, subcat, cat_id) in enumerate(subcats, 1):
        is_all = (cat_id == ALL_REF)
        if progress_cb:
            progress_cb({"event": "subcat_start",
                         "section": seccion or "Catálogo", "subcat": subcat or "todo",
                         "idx": idx, "total": total})
        offset = 0
        seen = 0
        while offset < _MAX_OFFSET:
            if is_all:
                url = f"{BASE}/products?offset={offset}&Nrpp={_PAGE}&totalResults=true"
            else:
                url = (f"{BASE}/products?categoryId={cat_id}&offset={offset}"
                       f"&Nrpp={_PAGE}&totalResults=true")
            try:
                data = _b.http_json(url)
            except Exception:
                break
            items = data.get("items") or []
            if not items:
                break
            for p in items:
                # En "todo el catálogo" la sección se deriva del route del producto.
                r = _extract(p, None if is_all else seccion,
                             None if is_all else subcat, book)
                rows.append(r); seen += 1
                if on_row:
                    on_row(r)
                if limit and seen >= limit:
                    break
            if progress_cb:
                progress_cb({"event": "subcat_page", "section": seccion, "subcat": subcat,
                             "page": offset // _PAGE + 1, "n_rows": len(rows)})
            total_res = data.get("totalResults", 0)
            if (limit and seen >= limit) or len(items) < _PAGE or offset + _PAGE >= (total_res or 0):
                break
            offset += _PAGE
        if progress_cb:
            progress_cb({"event": "subcat_done", "section": seccion, "subcat": subcat,
                         "idx": idx, "total": total, "n_rows": seen})
    if progress_cb:
        progress_cb({"event": "complete", "n_rows": len(rows)})
    return rows

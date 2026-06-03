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

# Selector de zona/tienda: en Imperial la zona ES un price-book (cambia el precio).
# Etiqueta que mostrará el launcher para el dropdown de zona.
ZONE_TITLE = "Zona (price-book Imperial)"
# Fallback estático (15 zonas) por si /priceListGroups no responde.
_ZONES_FALLBACK = ([("Base Price (Metropolitana)", "_default_price_book")]
                   + [(f"Zona {i:03d}", f"z{i:03d}") for i in range(1, 16) if i != 13])


def list_zones():
    """[(label, price_book_id), ...] desde /priceListGroups (cae al fallback)."""
    try:
        d = _b.http_json(f"{BASE}/priceListGroups?Nrpp=50")
        items = d.get("items") or []
        zs = [(pg.get("displayName") or pg.get("repositoryId"), pg.get("repositoryId"))
              for pg in items if pg.get("repositoryId")]
        # default primero
        zs.sort(key=lambda z: (z[1] != "_default_price_book", z[1]))
        if zs:
            return zs
    except Exception:
        pass
    return _ZONES_FALLBACK


# Lista de zonas para el selector del launcher (se resuelve en import; barato).
try:
    ZONES = list_zones()
except Exception:
    ZONES = _ZONES_FALLBACK

_PAGE = 250
_MAX_OFFSET = 20000


ALL_REF = "__ALL__"  # ref especial: enumerar el catálogo completo (sin precio)
_DISCOVER_PAGES = 60  # tope de páginas (×250) a escanear para armar el árbol
_DISCOVER_WORKERS = 8  # descargas en paralelo para que "Cargar secciones" no se cuelgue


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


def _snapshot_path():
    from pathlib import Path
    return Path(__file__).resolve().parent / "comp_imperial_tree.json"


def _load_snapshot():
    """Carga el árbol pre-cosechado del repo (carga instantánea). None si no hay."""
    import json
    try:
        p = _snapshot_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            # [[dept, [[label, leaf_id], ...]], ...] → tuplas
            return [(dept, [(lbl, lid) for lbl, lid in subs]) for dept, subs in data]
    except Exception:
        pass
    return None


def _save_snapshot(tree):
    """Best-effort: persiste el árbol cosechado (lo usa el script de mantención)."""
    import json
    try:
        _snapshot_path().write_text(json.dumps(tree, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    except Exception:
        pass


def discover_sections(progress_cb=None, force_live=False):
    """Árbol de catálogo de Imperial.

    Imperial detrás de Cloudflare rate-limitea las requests → cosechar el catálogo
    en vivo es lento (~minutos) y en Colab parecía "no cargar". Por eso se sirve un
    **snapshot pre-cosechado** (`comp_imperial_tree.json`, versionado en el repo) →
    carga instantánea. Si no existe (o `force_live`), cae al harvest en vivo y, si
    puede, escribe el snapshot (útil al regenerarlo desde el repo del mantenedor).
    """
    if not force_live:
        snap = _load_snapshot()
        if snap:
            if progress_cb:
                progress_cb({"event": "discover", "phase": "done",
                             "done": 1, "total": 1, "source": "snapshot"})
            return snap
    tree = _discover_sections_live(progress_cb)
    if tree:
        _save_snapshot(tree)
    return tree


def _discover_sections_live(progress_cb=None):
    """Cosecha el árbol real de catálogo del propio catálogo (en paralelo).

    Imperial (Oracle CC) tiene DOS taxonomías: la de navegación (rootCategory,
    sin productos directos, displayName nulos en profundidad) y la de catálogo
    (ids 00030003…, que SÍ devuelven productos con precio al filtrar por
    categoryId). El árbol de catálogo no es enumerable como colección, pero CADA
    producto trae su jerarquía completa en `parentCategories[].fixedParentCategories`
    (hoja → … → departamento → rootCategory). Acá se escanea el catálogo para
    reconstruir: departamento → categorías-hoja, con su conteo.

    El escaneo (~46 páginas) se hace **en paralelo** (ThreadPoolExecutor) para que
    no parezca colgado, e informa avance vía `progress_cb({"event":"discover", ...})`.

    Devuelve [(departamento, [(hoja (n), leaf_category_id), ...]), ...].
    El scrape posterior consulta por categoryId → ahí vienen los precios.
    """
    from concurrent.futures import ThreadPoolExecutor

    # 1) Primera página → totalResults para conocer cuántas páginas hay.
    if progress_cb:
        progress_cb({"event": "discover", "phase": "start", "done": 0, "total": 0})
    try:
        first = _b.http_json(f"{BASE}/products?offset=0&Nrpp={_PAGE}&totalResults=true")
    except Exception:
        return []
    total_res = first.get("totalResults", 0) or 0
    n_pages = min(_DISCOVER_PAGES, (total_res + _PAGE - 1) // _PAGE or 1)
    offsets = [i * _PAGE for i in range(1, n_pages)]  # la página 0 ya la tenemos

    pages = {0: first.get("items") or []}

    def _fetch(off):
        try:
            return off, (_b.http_json(
                f"{BASE}/products?offset={off}&Nrpp={_PAGE}").get("items") or [])
        except Exception:
            return off, []

    done = 1
    if progress_cb:
        progress_cb({"event": "discover", "phase": "scan", "done": done, "total": n_pages})
    with ThreadPoolExecutor(max_workers=_DISCOVER_WORKERS) as ex:
        for off, items in ex.map(_fetch, offsets):
            pages[off] = items
            done += 1
            if progress_cb and done % 4 == 0:
                progress_cb({"event": "discover", "phase": "scan", "done": done, "total": n_pages})

    # 2) Cosechar departamento → hojas.
    depts = {}      # {dept_id: {"name":?, "leaves": {leaf_id: {"name":?, "count":int}}}}
    for off in sorted(pages):
        for p in pages[off]:
            name = _slug_name(p.get("route", ""))
            for pc in (p.get("parentCategories") or []):
                leaf_id = pc.get("repositoryId")
                if not leaf_id:
                    continue
                dept_id = _dept_of(pc) or leaf_id
                d = depts.setdefault(dept_id, {"name": None, "leaves": {}})
                lf = d["leaves"].setdefault(leaf_id, {"name": name, "count": 0})
                lf["count"] += 1
                break  # solo la categoría primaria del producto

    # 3) Resolver nombre de cada departamento (en paralelo, ~15 queries).
    if progress_cb:
        progress_cb({"event": "discover", "phase": "names", "done": n_pages, "total": n_pages})

    def _dept_name(dept_id):
        try:
            r = _b.http_json(f"{BASE}/products?categoryId={dept_id}&offset=0&Nrpp=1")
            return dept_id, (r.get("category") or {}).get("displayName")
        except Exception:
            return dept_id, None

    with ThreadPoolExecutor(max_workers=_DISCOVER_WORKERS) as ex:
        for dept_id, nm in ex.map(_dept_name, list(depts)):
            if nm:
                depts[dept_id]["name"] = nm

    out = []
    for dept_id, d in depts.items():
        dept_name = d["name"] or f"Departamento {dept_id}"
        subs = [(f"{lf['name']} ({lf['count']})", lid)
                for lid, lf in sorted(d["leaves"].items(), key=lambda kv: kv[1]["name"])]
        if subs:
            out.append((dept_name, subs))
    out.sort(key=lambda x: x[0])
    if progress_cb:
        progress_cb({"event": "discover", "phase": "done", "done": n_pages, "total": n_pages})
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


def _img_url(p):
    """URL absoluta de la imagen (thumb) del producto Oracle CC."""
    rel = p.get("primaryThumbImageURL") or p.get("primaryFullImageURL") or ""
    if not rel:
        return ""
    return rel if rel.startswith("http") else f"{SITE}{rel}"


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
        url=f"{SITE}{route}" if route else "", img=_img_url(p),
    )


def scrape_section(subcats, *, on_row=None, progress_cb=None, limit=None,
                   zone=None, zone_price_book=None):
    """subcats: [(sección, subcategoría, category_repoId), ...]. Devuelve filas.

    `zone` (o el alias `zone_price_book`) = price-book a aplicar: en Imperial la
    zona cambia el precio (default `_default_price_book` = Metropolitana).
    """
    book = zone or zone_price_book or ZONE_PRICE_BOOK
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

# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Engine Portal Inmobiliario (portalinmobiliario.com).

Portal Inmobiliario corre sobre la infraestructura de **MercadoLibre** y renderiza
sus páginas **server-side** con todo el estado embebido como JSON (`_n.ctx.r = {…}`)
dentro del HTML. La API pública de búsqueda de ML está gateada (403 anónimo), pero
NO hace falta: el HTML de resultados ya trae los avisos en
`appProps.pageProps.initialState.results` (polycards). Extracción 100% HTTP plano
(urllib) + parse JSON, sin navegador, sin auth, sin Cloudflare. Es el patrón
Tier-A/PCFactory pero leyendo el estado SSR en vez de una API REST.

Verificado en vivo (2026-07-17):
- Listado: `/{operacion}/{tipo}/{ubicacion}` (+ `/_Desde_N` para paginar, 48/pág).
  Cada polycard trae id, permalink, precio (UF/CLF o CLP), atributos
  (dormitorios/baños/m²), ubicación, vendedor, entrega, unidades, foto.
- Detalle (permalink del aviso): otro estado SSR con `technical_specifications`
  (16–46 atributos: superficie total/útil, orientación, antigüedad, gastos
  comunes, estacionamientos, bodegas…), descripción, dirección exacta, UF+CLP,
  galería. La función `detail()` lo extrae (para un modo "ficha completa" futuro);
  el modo por defecto del launcher es SOLO LISTADO (rápido).

Sin dependencia de `requests` (urllib stdlib) → testeable fuera de Colab.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.request

BASE = "https://www.portalinmobiliario.com"
PAGE_SIZE = 48

# Enums para la UI (slugs verificados en la estructura de URL de Portal).
OPERATIONS = [("Venta", "venta"), ("Arriendo", "arriendo"),
              ("Arriendo temporal", "arriendo-temporal")]
PROPERTY_TYPES = [
    ("Departamento", "departamento"), ("Casa", "casa"), ("Oficina", "oficina"),
    ("Local comercial", "local-comercial"), ("Bodega", "bodega"),
    ("Estacionamiento", "estacionamiento"), ("Sitio", "sitio"),
    ("Parcela", "parcela"), ("Terreno", "terreno"),
    ("Industrial", "industrial"), ("Agrícola", "agricola"),
]

OUTPUT_COLS = [
    "Portal", "ID", "Operación", "Tipo", "Título", "Precio", "Moneda",
    "Dormitorios", "Baños", "Superficie", "Atributos", "Ubicación",
    "Vendedor", "Entrega", "Unidades", "Publicidad", "URL",
]

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_CURRENCY = {"CLF": "UF", "CLP": "$"}


# ── HTTP + parse del estado SSR ─────────────────────────────────────────────
def _get(url, *, retries=4, timeout=40):
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(0.6 * (a + 1))
    return None


def _extract_state(html):
    """Devuelve el objeto JSON del estado SSR embebido (`_n.ctx.r = {…}`)."""
    if not html:
        return None
    for s in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
        if '"appProps"' not in s or '"initialState"' not in s:
            continue
        start = s.find("{")
        depth = 0; instr = False; esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if esc: esc = False; continue
            if ch == "\\": esc = True; continue
            if ch == '"': instr = not instr
            if instr: continue
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except Exception:
                        break
    return None


def _components_map(poly):
    out = {}
    for c in poly.get("components", []):
        t = c.get("type")
        if t and isinstance(c.get(t), dict):
            out[t] = c[t]
    return out


def _collect_polys(o, acc):
    if isinstance(o, dict):
        if isinstance(o.get("polycard"), dict) and o["polycard"].get("metadata"):
            acc.append(o["polycard"])
        for v in o.values():
            _collect_polys(v, acc)
    elif isinstance(o, list):
        for v in o:
            _collect_polys(v, acc)


def _split_attrs(texts):
    """De ['1 a 2 dormitorios','2 baños','29 - 62 m² útiles'] saca dorm/baños/m²."""
    dorm = banos = sup = ""
    for t in texts:
        tl = t.lower()
        if "dormitor" in tl:
            dorm = t
        elif "baño" in tl or "bano" in tl:
            banos = t
        elif "m²" in tl or "m2" in tl or "hectárea" in tl:
            sup = t
    return dorm, banos, sup


def _img_url(picid):
    return f"https://http2.mlstatic.com/D_NQ_NP_2X_{picid}-F.webp" if picid else ""


def parse_listing(poly, *, operacion="", tipo=""):
    md = poly.get("metadata", {})
    cm = _components_map(poly)
    price = cm.get("price", {}).get("current_price", {})
    texts = cm.get("attributes_list", {}).get("texts", [])
    dorm, banos, sup = _split_attrs(texts)
    seller = (cm.get("seller", {}).get("text") or "").replace("{icon_cockade}", "").strip()
    pics = poly.get("pictures", {}).get("pictures", [])
    url = md.get("url", "") or ""
    if "/MLC-" not in url:
        permalink = ""
    elif url.startswith("http"):
        permalink = url
    else:
        permalink = "https://" + url.lstrip("/")
    cur = price.get("currency")
    return {
        "Portal": "Portal Inmobiliario",
        "ID": md.get("id"),
        "Operación": operacion,
        "Tipo": tipo,
        "Título": cm.get("title", {}).get("text", ""),
        "Precio": price.get("value"),
        "Moneda": _CURRENCY.get(cur, cur or ""),
        "Dormitorios": dorm,
        "Baños": banos,
        "Superficie": sup,
        "Atributos": " | ".join(texts),
        "Ubicación": cm.get("location", {}).get("text", ""),
        "Vendedor": seller,
        "Entrega": cm.get("possession_date", {}).get("text", ""),
        "Unidades": cm.get("available_units", {}).get("text", ""),
        "Publicidad": "Sí" if md.get("is_pad") == "true" else "",
        "URL": permalink,
        "_img": _img_url(pics[0].get("id") if pics else None),
    }


# ── Paginación de búsqueda ──────────────────────────────────────────────────
def _page_url(base_url, offset):
    """Inserta `/_Desde_N` en la URL de búsqueda (48/pág). Preserva query string."""
    if offset <= 0:
        return base_url
    path, _, query = base_url.partition("?")
    path = re.sub(r"/_Desde_\d+", "", path).rstrip("/")
    path = f"{path}/_Desde_{offset + 1}"
    return f"{path}?{query}" if query else path


def _state_results(state):
    try:
        return state["appProps"]["pageProps"]["initialState"]["results"]
    except Exception:
        return None


def _pagination(state):
    def find(o, k, d=0):
        if d > 8: return None
        if isinstance(o, dict):
            if k in o: return o[k]
            for v in o.values():
                r = find(v, k, d + 1)
                if r is not None: return r
        elif isinstance(o, list):
            for v in o:
                r = find(v, k, d + 1)
                if r is not None: return r
        return None
    return find(state, "pagination") or {}


def build_url(operacion, tipo, ubicacion):
    """URL de búsqueda a partir de operación (slug), tipo (slug) y ubicación (slug)."""
    ubic = (ubicacion or "").strip().strip("/")
    return f"{BASE}/{operacion}/{tipo}/{ubic}" if ubic else f"{BASE}/{operacion}/{tipo}"


def search(base_url, *, operacion="", tipo="", max_pages=1, include_ads=True,
           on_row=None, page_cb=None, seen=None):
    """Pagina una URL de búsqueda y devuelve las filas del listado (dedup por ID).

    Args:
      base_url: URL de resultados de Portal Inmobiliario (de build_url o pegada).
      max_pages: tope de páginas (48 avisos c/u).
      include_ads: si False, descarta los avisos marcados como publicidad.
      on_row: callback(row) por fila nueva. page_cb: callback(page, new, total_pages).
    """
    rows = []
    seen = seen if seen is not None else set()
    total_pages = None
    for page in range(max_pages):
        state = _extract_state(_get(_page_url(base_url, page * PAGE_SIZE)))
        if not state:
            break
        results = _state_results(state)
        if results is None:
            break
        if total_pages is None:
            total_pages = (_pagination(state) or {}).get("page_count")
        polys = []
        _collect_polys(results, polys)
        new = 0
        for p in polys:
            r = parse_listing(p, operacion=operacion, tipo=tipo)
            if not r["ID"] or r["ID"] in seen:
                continue
            if not include_ads and r["Publicidad"]:
                continue
            seen.add(r["ID"])
            rows.append(r)
            new += 1
            if on_row:
                on_row(r)
        if page_cb:
            page_cb(page + 1, new, total_pages)
        if new == 0:
            break
    return rows


# ── Detalle (ficha completa) — para un modo futuro; el launcher usa solo listado ──
def _grab(o, cid):
    if isinstance(o, dict):
        if (o.get("component_id") or o.get("id")) == cid or o.get("type") == cid:
            return o
        for v in o.values():
            r = _grab(v, cid)
            if r is not None: return r
    elif isinstance(o, list):
        for v in o:
            r = _grab(v, cid)
            if r is not None: return r
    return None


def _deep(o, key, d=0):
    if d > 9: return None
    if isinstance(o, dict):
        if key in o: return o[key]
        for v in o.values():
            r = _deep(v, key, d + 1)
            if r is not None: return r
    elif isinstance(o, list):
        for v in o:
            r = _deep(v, key, d + 1)
            if r is not None: return r
    return None


def detail(permalink):
    """Extrae los campos ricos del detalle (descripción, dirección, UF+CLP, specs)."""
    state = _extract_state(_get(permalink))
    if not state:
        return {}
    comp = _deep(state, "components") or {}
    out = {"URL": permalink}
    d = _grab(comp, "description")
    if isinstance(d, dict):
        out["Descripción"] = d.get("content", "")
    loc = _grab(comp, "location") or _grab(comp, "location_and_points")
    if isinstance(loc, dict):
        rows = loc.get("content_rows") or []
        out["Dirección"] = (_deep(rows[0], "text") if rows else _deep(loc, "text")) or ""
    pr = _grab(comp, "price")
    if isinstance(pr, dict):
        p = pr.get("price", {})
        out["Precio UF"] = p.get("value") if p.get("currency_id") == "CLF" else None
        out["Precio CLP"] = _deep(pr.get("subtitles", []), "value")
    specs = {}
    ts = _grab(comp, "technical_specifications")
    if isinstance(ts, dict):
        for section in ts.get("specs", []):
            for a in section.get("attributes", []):
                k, v = a.get("id"), a.get("text")
                if k and v:
                    specs[k] = v
    out["specs"] = specs
    gal = _grab(comp, "gallery") or _grab(comp, "gallery_mosaic")
    pics = []
    if isinstance(gal, dict):
        for pp in (gal.get("pictures") or gal.get("items") or gal.get("slides") or []):
            pid = pp.get("id") if isinstance(pp, dict) else None
            if pid: pics.append(pid)
    out["N° Fotos"] = len(pics)
    return out


# ── Excel (estética unificada del proyecto) ─────────────────────────────────
def write_excel(rows, path, *, columns=None, with_images=False):
    import openpyxl
    from engines._excel_utils import apply_clean_style
    from engines.pcf_base import _embed_images

    cols = list(columns or OUTPUT_COLS)
    if with_images:
        cols = cols + ["Imagen"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Avisos"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    apply_clean_style(ws, skip_width=("URL", "Imagen"))
    if with_images:
        _embed_images(ws, rows, len(cols))
    wb.save(path)

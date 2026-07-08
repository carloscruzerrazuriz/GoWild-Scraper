# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Scraper interactivo de productos vendidos por Sodimac, por sección.

Flujo:
  1. Setea zona Metropolitana / Cerrillos (modificable).
  2. Descubre las secciones top-level del megamenu de Sodimac.
  3. El usuario elige una sección con un menú interactivo.
  4. Descubre subcategorías de la sección desde __NEXT_DATA__.
  5. Scrapea cada subcategoría paginando, filtrando productos vendidos por Sodimac.
  6. Captura todos los campos extraíbles del card.
  7. Exporta Excel con imágenes embebidas.
"""

import os
import re
import json
import asyncio
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, MofNCompleteColumn,
)
from rich import box

console = Console()

BASE_URL = "https://www.sodimac.cl/sodimac-cl"
# Resolve project dir from this file's location so the scraper is portable
# (works from local checkout, Colab, or any other host).
try:
    PROJECT_DIR = Path(__file__).resolve().parent
except NameError:
    PROJECT_DIR = Path.cwd()
SCREENSHOT_DIR = PROJECT_DIR / "cards_screenshots"
PARTIAL_DIR = PROJECT_DIR / "partial_runs"
PROJECT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
PARTIAL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_REGION = "Metropolitana"
DEFAULT_COMUNA = "Cerrillos"
MAX_PAGES_PER_SUBCAT = 200

# All Sodimac DOM selectors live here — when the front rebuilds, fix them in one place.
SELECTORS = {
    "card": 'div[class*="grid-pod"]',
    "marca": ".pod-title",
    "descripcion": ".pod-subTitle",
    "vendedor": '.pod-sellerText, [class*="pod-seller"], [class*="sellerText"]',
    "link": 'a[href*="/articulo/"], a[href*="/product/"]',
    "badge": '.pod-badges-item, [class*="Badge"]',
    "wholesale": '.wholesale-container, [class*="wholesale"]',
    "wholesale_label": '.bottom-text, [class*="bottom-text"]',
    "price_span": '.prices-0 span[class*="copy"], [class*="prices"] span[class*="copy"]',
    "strikethrough": 's, del, [class*="line-through"], [class*="crossed"], [class*="strikethrough"]',
    "discount_badge": '[class*="discount-badge-item"], [class*="discount-badge"]',
    "pagination_next": 'button#testId-pagination-top-arrow-right',
    "no_results": '[class*="no-results"], [class*="empty-results"], [class*="without-results"]',
}

SODIMAC_SELLER_FACET = "facetSelected=true&f.derived.variant.sellerId=SODIMAC"


class PartialWriter:
    """Append-only JSONL writer so scrapes longer than minutes survive crashes.

    File lives at PARTIAL_DIR/{run_id}.jsonl and is flushed on every row.
    Read it back with `PartialWriter.load(path)` to recover a run.
    """
    def __init__(self, run_id, append=False):
        self.path = PARTIAL_DIR / f"{run_id}.jsonl"
        mode = "a" if append else "w"
        self._fh = open(self.path, mode, encoding="utf-8")
        self.count = 0

    def write(self, row):
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()
        self.count += 1

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    @staticmethod
    def load(path):
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

ALL_STORES = [
    {"id": "E534", "name": "Antofagasta",   "region": "Antofagasta",   "comuna": "Antofagasta"},
    {"id": "E619", "name": "Arica",         "region": "Arica",         "comuna": "Arica"},
    {"id": "E633", "name": "Bio Bio",       "region": "Biobío",        "comuna": "Hualpén"},
    {"id": "E614", "name": "Calama",        "region": "Antofagasta",   "comuna": "Calama"},
    {"id": "E522", "name": "Cerrillos",     "region": "Metropolitana", "comuna": "Cerrillos"},
    {"id": "E988", "name": "Chicureo",      "region": "Metropolitana", "comuna": "Colina"},
    {"id": "E990", "name": "Chiguayante",   "region": "Biobío",        "comuna": "Chiguayante"},
    {"id": "E525", "name": "Chillán",       "region": "Ñuble",         "comuna": "Chillán"},
    {"id": "E760", "name": "Copiapó",       "region": "Atacama",       "comuna": "Copiapó"},
    {"id": "E983", "name": "Coronel",       "region": "Biobío",        "comuna": "Coronel"},
    {"id": "E511", "name": "Costanera",     "region": "Metropolitana", "comuna": "Providencia"},
    {"id": "E592", "name": "Curicó",        "region": "Maule",         "comuna": "Curicó"},
    {"id": "E781", "name": "El Belloto",    "region": "Valparaíso",    "comuna": "Quilpué"},
    {"id": "E513", "name": "El Llano",      "region": "Metropolitana", "comuna": "San Miguel"},
    {"id": "E510", "name": "Florida",       "region": "Metropolitana", "comuna": "La Florida"},
    {"id": "E502", "name": "Kennedy",       "region": "Metropolitana", "comuna": "Las Condes"},
    {"id": "E514", "name": "La Dehesa",     "region": "Metropolitana", "comuna": "Lo Barnechea"},
    {"id": "E512", "name": "La Reina",      "region": "Metropolitana", "comuna": "La Reina"},
    {"id": "E521", "name": "La Serena",     "region": "Coquimbo",      "comuna": "La Serena"},
    {"id": "E744", "name": "La Unión",      "region": "Ríos",          "comuna": "La Unión"},
    {"id": "E524", "name": "Linares",       "region": "Maule",         "comuna": "Linares"},
    {"id": "E900", "name": "Los Andes",     "region": "Valparaíso",    "comuna": "Los Andes"},
    {"id": "E529", "name": "Los Ángeles",   "region": "Biobío",        "comuna": "Los Ángeles"},
    {"id": "E503", "name": "Maipú",         "region": "Metropolitana", "comuna": "Maipú"},
    {"id": "E643", "name": "Ochagavía",     "region": "Metropolitana", "comuna": "Pedro Aguirre Cerda"},
    {"id": "E585", "name": "Osorno",        "region": "Lagos",         "comuna": "Osorno"},
    {"id": "E775", "name": "Portal Ñuñoa",  "region": "Metropolitana", "comuna": "Ñuñoa"},
    {"id": "E748", "name": "Portal Osorno", "region": "Lagos",         "comuna": "Osorno"},
    {"id": "E506", "name": "Portal Temuco", "region": "Araucanía",     "comuna": "Temuco"},
    {"id": "E659", "name": "Puente Alto",   "region": "Metropolitana", "comuna": "Puente Alto"},
    {"id": "E507", "name": "Puerto Montt",  "region": "Lagos",         "comuna": "Puerto Montt"},
    {"id": "E655", "name": "Quilicura",     "region": "Metropolitana", "comuna": "Quilicura"},
    {"id": "E518", "name": "Quilín",        "region": "Metropolitana", "comuna": "Peñalolén"},
    {"id": "E646", "name": "Quillota",      "region": "Valparaíso",    "comuna": "Quillota"},
    {"id": "E504", "name": "Rancagua",      "region": "O'Higgins",     "comuna": "Rancagua"},
    {"id": "E843", "name": "San Bernardo",  "region": "Metropolitana", "comuna": "San Bernardo"},
    {"id": "E874", "name": "Santa Amalia",  "region": "Metropolitana", "comuna": "La Florida"},
    {"id": "E591", "name": "Talca",         "region": "Maule",         "comuna": "Talca"},
    {"id": "E517", "name": "Temuco",        "region": "Araucanía",     "comuna": "Temuco"},
    {"id": "E520", "name": "Valparaíso",    "region": "Valparaíso",    "comuna": "Valparaíso"},
    {"id": "E830", "name": "Villarrica",    "region": "Araucanía",     "comuna": "Villarrica"},
    {"id": "E508", "name": "Viña del Mar",  "region": "Valparaíso",    "comuna": "Viña del Mar"},
]

QSTYLE = QStyle([
    ("qmark", "fg:#00bcd4 bold"),
    ("question", "bold"),
    ("answer", "fg:#00d97e bold"),
    ("pointer", "fg:#00bcd4 bold"),
    ("highlighted", "fg:#00bcd4 bold"),
    ("selected", "fg:#00d97e"),
    ("instruction", "fg:#888888"),
])


# ─────────────────────────────────────────  Zone & autocomplete  ───────────

# ── Zona: delegado al sistema ÚNICO compartido (engines/_zone_sodimac.py) ──
# Antes Sección tenía su propia set_zone SIN verificación (devolvía True a
# ciegas → podía scrapear con la zona equivocada) y SIN warmup. Ahora usa la
# misma implementación robusta que MK7/Ferni: verifica por cookie+label y hace
# warmup anti-Cloudflare. Mismos nombres → cero cambios en los call-sites.
from engines import _zone_sodimac as _zone

_type_autocomplete  = _zone._type_autocomplete
set_zone            = _zone.set_zone
set_zone_with_retry = _zone.set_zone_with_retry


# ─────────────────────────────────────────  Discovery  ─────────────────────

async def discover_sections(page):
    """Devuelve lista de (section_name, [(subcat_name, subcat_url), ...]).

    Lee sisNavigationMenu.entry.categories del __NEXT_DATA__ de la home y
    aplana cada categoría top-level con sus second_level_categories.
    """
    import json
    from datetime import datetime
    cache_path = PROJECT_DIR / f"sections_cache_sodimac_{datetime.now().strftime('%Y%m%d')}.json"
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    await page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2500)
    html = await page.content()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        cats = data["props"]["pageProps"]["serverData"]["headerData"]["sisNavigationMenu"]["entry"]["categories"]
    except Exception:
        return []

    sections = []
    seen_names = set()
    for c in cats:
        title = (c.get("title") or "").strip()
        if not title or title in seen_names:
            continue
        if re.search(r'campañ|cyber|revancha|servicio|asesor', title, re.I):
            continue
        subs = []
        for s in c.get("second_level_categories", []) or []:
            n = (s.get("item_name") or "").strip()
            u = (s.get("item_url") or "").strip()
            if n and u and u.startswith("http") and "isLanding=true" not in u:
                subs.append((n, u))
        if not subs:
            continue
        seen_names.add(title)
        sections.append((title, subs))
    sections.sort(key=lambda x: x[0])
    
    if sections:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(sections, f, ensure_ascii=False)
        except Exception:
            pass
            
    return sections




# ─────────────────────────────────────────  Scraping  ──────────────────────


# JS that extracts ALL cards on the current page in one bridge round-trip.
# Returns an array of dicts keyed by SELECTORS — must match Python keys exactly.
def _build_extract_all_js(section_name, subcat_name):
    sel = SELECTORS
    return f"""(args) => {{
        const SEL = args.sel;
        const sectionName = args.section;
        const subcatName = args.subcat;
        const cards = [...document.querySelectorAll(SEL.card)];
        const norm = (s) => (s || "").replace(/\\s+/g, ' ').trim();

        return cards.map(card => {{
            const text = (s) => {{
                const el = card.querySelector(s);
                return el ? norm(el.innerText) : "";
            }};
            const marca = text(SEL.marca);
            const desc = text(SEL.descripcion);
            const sellerEl = card.querySelector(SEL.vendedor);
            let vendedor = sellerEl ? norm(sellerEl.innerText).replace(/^Por\\s+/i, '') : "";
            if (!vendedor) {{
                const all = card.innerText || "";
                const m = all.match(/Por\\s+([A-Z0-9 ]{{2,30}})/);
                if (m) vendedor = m[1].trim();
            }}
            const a = card.querySelector(SEL.link);
            const href = a ? a.href : "";
            let sku = "";
            if (href) {{
                const parts = href.split('?')[0].split('/').filter(Boolean);
                sku = parts[parts.length - 1];
            }}

            let precios_congelados = "No";
            const badges = card.querySelectorAll(SEL.badge);
            for (const b of badges) {{
                if ((b.innerText || '').includes("Precios Congelados")) {{ precios_congelados = "Si"; break; }}
            }}

            let precio_mayorista = "", descuento_mayorista = "";
            const wc = card.querySelector(SEL.wholesale);
            if (wc) {{
                const bt = wc.querySelector(SEL.wholesale_label);
                descuento_mayorista = bt ? norm(bt.innerText) : "";
                const pm = wc.querySelector('.prices-0 span[class*="copy10"], span[class*="copy10"]');
                precio_mayorista = pm ? norm(pm.innerText) : "";
            }}

            const priceSpans = [...card.querySelectorAll(SEL.price_span)];
            const allPrices = priceSpans.map(p => norm(p.innerText)).filter(t => /\\$/.test(t));

            let precio_internet = "";
            for (const p of priceSpans) {{
                if (wc && wc.contains(p)) continue;
                const t = (p.innerText || '').trim();
                if (/\\$/.test(t)) {{ precio_internet = norm(t); break; }}
            }}

            let precio_normal = "";
            const strike = card.querySelector(SEL.strikethrough);
            if (strike) precio_normal = norm(strike.innerText);

            let precio_cmr = "";
            const cmrLabel = [...card.querySelectorAll('*')].find(e => {{
                const t = (e.innerText || '').trim();
                return t && t.length < 50 && /\\bCMR\\b/.test(t) && /\\$/.test(t);
            }});
            if (cmrLabel) {{
                const m = (cmrLabel.innerText || '').match(/\\$\\s*[\\d.,]+/);
                if (m) {{
                    const candidate = norm(m[0]);
                    const intDigits = (precio_internet || '').replace(/\\D/g, '');
                    const cmrDigits = candidate.replace(/\\D/g, '');
                    if (cmrDigits && cmrDigits !== intDigits) precio_cmr = candidate;
                }}
            }}

            let pct_descuento = "";
            const pctRegex = /-?\\d{{1,3}}\\s*%/;
            const discBadge = card.querySelector(SEL.discount_badge);
            if (discBadge) {{
                const m = (discBadge.innerText || '').match(pctRegex);
                if (m) pct_descuento = m[0];
            }}
            if (!pct_descuento) {{
                for (const b of badges) {{
                    const t = (b.innerText || '').trim();
                    if (pctRegex.test(t) && !/desde/i.test(t)) {{ pct_descuento = t.match(pctRegex)[0]; break; }}
                }}
            }}

            return {{
                "Sección": sectionName,
                "Subcategoría": subcatName,
                "Vendedor": vendedor,
                "Marca": marca,
                "SKU": sku,
                "Descripción Producto": desc,
                "Precios Congelados": precios_congelados,
                "Precio Normal": precio_normal,
                "Precio Internet": precio_internet,
                "% Descuento": pct_descuento,
                "Precio CMR": precio_cmr,
                "Precio Mayorista": precio_mayorista,
                "Descuento Mayorista": descuento_mayorista,
                "Todos los Precios": allPrices.join(" | "),
                "URL": href,
            }};
        }});
    }}"""


async def _safe_goto(page, url, retries=2, timeout=60000):
    last_err = None
    for attempt in range(retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            last_err = e
            if attempt < retries:
                await page.wait_for_timeout(1500 * (attempt + 1))
    return False


_BREADCRUMB_JS = """() => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
        try {
            const j = JSON.parse(s.textContent);
            const arr = Array.isArray(j) ? j : [j];
            for (const obj of arr) {
                if (obj && obj['@type'] === 'BreadcrumbList' && Array.isArray(obj.itemListElement)) {
                    const items = obj.itemListElement
                        .slice()
                        .sort((a, b) => (a.position || 0) - (b.position || 0))
                        .map(e => (e.name || '').trim())
                        .filter(Boolean);
                    return items;
                }
            }
        } catch (e) {}
    }
    return [];
}"""


async def _detect_breadcrumb(page):
    """Devuelve (section, subcat) parseados del JSON-LD, o (None, None) si no hay.

    Sodimac usa position=0 para la hoja y posiciones mayores para ancestros.
    Cuando solo viene un crumb con formato "X - Y", lo dividimos en sección/subcat.
    """
    try:
        items = await page.evaluate(_BREADCRUMB_JS)
    except Exception:
        return None, None
    if not items:
        return None, None
    leaf = items[0]
    if len(items) >= 2:
        section = items[-1]
        if " - " in section and leaf != section:
            section = section.split(" - ", 1)[0].strip()
        return section, leaf
    if " - " in leaf:
        sec, sub = leaf.split(" - ", 1)
        return sec.strip(), sub.strip()
    return leaf, leaf


async def scrape_subcat(page, section_name, subcat_name, subcat_url, progress, page_task,
                        capture_screenshots=True, only_sodimac=True, page_progress_cb=None,
                        auto_breadcrumb=False):
    """Scrapea una subcategoría paginando.

    Devuelve dict: {
      "rows": [..],          # filas crudas (sin filtrar Sodimac)
      "pages": int,          # páginas leídas
      "truncated": bool,     # alcanzó MAX_PAGES_PER_SUBCAT
      "failed": bool,        # falla irrecuperable (goto)
      "empty": bool,         # PLP cargó pero sin productos
    }
    """
    result = {"rows": [], "pages": 0, "truncated": False, "failed": False, "empty": False}
    facet = SODIMAC_SELLER_FACET if only_sodimac else None
    if facet:
        sep = "&" if "?" in subcat_url else "?"
        subcat_url = f"{subcat_url}{sep}{facet}"

    if not await _safe_goto(page, subcat_url):
        result["failed"] = True
        return result

    seen_in_subcat = set()
    extract_js = _build_extract_all_js(section_name, subcat_name)
    page_num = 1
    total_pages = None  # se detecta al leer el paginador en cada pagina
    # base_url se inicializa con la URL real de la pagina cargada (Sodimac
    # agrega query params como store=so_acom_XXX que son necesarios para
    # preservar el contexto de tienda al navegar a otras paginas).
    base_url = None
    breadcrumb_applied = not auto_breadcrumb
    result["section_resolved"] = section_name
    result["subcat_resolved"] = subcat_name

    while True:
        # Wait for grid OR for explicit empty-state to appear, whichever comes first.
        try:
            await page.wait_for_selector(
                f'{SELECTORS["card"]}, {SELECTORS["no_results"]}',
                timeout=15000,
            )
        except Exception:
            # Neither grid nor empty-state appeared — treat as failure of this page.
            if page_num == 1:
                result["empty"] = True
            break

        # If empty-state is visible and there are no cards, stop cleanly.
        has_cards = await page.evaluate(
            f"() => document.querySelectorAll({json.dumps(SELECTORS['card'])}).length"
        )
        if not has_cards:
            if page_num == 1:
                result["empty"] = True
            break

        await page.wait_for_timeout(1500)

        if not breadcrumb_applied:
            sec_bc, sub_bc = await _detect_breadcrumb(page)
            if sec_bc or sub_bc:
                section_name = sec_bc or section_name
                subcat_name = sub_bc or subcat_name
                extract_js = _build_extract_all_js(section_name, subcat_name)
                result["section_resolved"] = section_name
                result["subcat_resolved"] = subcat_name
            breadcrumb_applied = True

        # Remove overlays + lazy-load via scroll
        await page.evaluate("""() => {
            const r = () => document.querySelectorAll('[data-testid="overlay"], [class*="overlay"], [class*="Modal"], [class*="Tooltip"]').forEach(o => o.remove());
            r(); setTimeout(r, 500);
        }""")
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(250)

        # Esperar a que los precios terminen de renderizar (client-side) antes de extraer.
        # Misma carrera que en MK7: la grilla carga antes que los precios visibles del DOM.
        # Poll hasta que el nº de tarjetas con precio se estabilice (2 ticks iguales >0) o
        # timeout ~8s. La estabilización tolera productos sin stock que nunca muestran precio.
        _price_ready_js = (
            "() => {"
            "  const cards = [...document.querySelectorAll(" + json.dumps(SELECTORS["card"]) + ")];"
            "  let withPrice = 0;"
            "  for (const c of cards) {"
            "    const spans = [...c.querySelectorAll(" + json.dumps(SELECTORS["price_span"]) + ")];"
            "    if (spans.some(s => /\\$/.test((s.innerText || '')))) withPrice++;"
            "  }"
            "  return {total: cards.length, withPrice};"
            "}"
        )
        _prev_count, _stable_ticks = -1, 0
        for _ in range(16):  # 16 * 500ms = 8s máx
            try:
                _stat = await page.evaluate(_price_ready_js)
            except Exception:
                _stat = None
            _cur = _stat.get("withPrice", 0) if _stat else 0
            if _cur > 0 and _cur == _prev_count:
                _stable_ticks += 1
                if _stable_ticks >= 2:
                    break
            else:
                _stable_ticks = 0
            _prev_count = _cur
            await page.wait_for_timeout(500)

        # ONE evaluate per page extracts all cards in the current grid.
        page_data = await page.evaluate(extract_js, {"sel": SELECTORS, "section": section_name, "subcat": subcat_name})

        if capture_screenshots:
            cards = await page.query_selector_all(SELECTORS["card"])
            for i, card in enumerate(cards):
                if i >= len(page_data):
                    break
                sku = page_data[i].get("SKU") or f"unknown_{page_num}_{i}"
                img_path = SCREENSHOT_DIR / f"{sku}.jpg"
                if not img_path.exists():
                    try:
                        await card.scroll_into_view_if_needed()
                        await card.screenshot(path=str(img_path), type="jpeg", quality=80)
                    except Exception:
                        pass
                page_data[i]["Image Path"] = str(img_path)
        else:
            for d in page_data:
                d["Image Path"] = ""

        if not page_data:
            break

        new_in_page = 0
        for d in page_data:
            sku = d.get("SKU")
            if sku and sku not in seen_in_subcat:
                seen_in_subcat.add(sku)
                result["rows"].append(d)
                new_in_page += 1

        result["pages"] = page_num

        # Capturar la URL real de la pagina (Sodimac agrega params como
        # store=so_acom_XXX que necesitamos preservar al navegar a otras
        # paginas). Lo hacemos despues de page 1 confirmada con cards.
        if base_url is None:
            try:
                base_url = page.url
            except Exception:
                base_url = subcat_url

        # Detectar total_pages: scroll al paginador, esperar a que aparezca,
        # leer todos los botones numericos. Mas robusto que un solo wait_for_timeout.
        try:
            # Asegurar que el paginador este en viewport (puede estar al fondo)
            await page.evaluate("""() => {
                const p = document.querySelector('[id^="testId-pagination-top-"]');
                if (p) p.scrollIntoView({behavior:'instant', block:'center'});
            }""")
            await page.wait_for_timeout(400)
        except Exception:
            pass
        try:
            detected_total = await page.evaluate("""() => {
                // Buscar TODOS los nodos del paginador (top y bottom).
                const nodes = document.querySelectorAll('[id^="testId-pagination-"]');
                let max = 1;
                nodes.forEach(n => {
                    // El numero puede estar en textContent o aria-label
                    const txt = ((n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '')).trim();
                    // Buscar todos los enteros y quedarnos con el mayor
                    const matches = txt.match(/\\d+/g) || [];
                    matches.forEach(m => {
                        const num = parseInt(m, 10);
                        if (!isNaN(num) && num > max && num < 1000) max = num;
                    });
                });
                return max;
            }""")
        except Exception:
            detected_total = None
        if detected_total and detected_total > 1:
            if total_pages is None or detected_total > total_pages:
                total_pages = detected_total

        try:
            progress.update(page_task, description=f"  └─ {subcat_name} · pág {page_num}{'/' + str(total_pages) if total_pages else ''} · {len(result['rows'])} cards")
        except Exception:
            pass

        if page_progress_cb is not None:
            try:
                page_progress_cb(page_num, total_pages)
            except Exception:
                pass

        # ¿Hay mas paginas?
        if total_pages and page_num >= total_pages:
            break

        next_page_num = page_num + 1
        if next_page_num > MAX_PAGES_PER_SUBCAT:
            result["truncated"] = True
            break

        # Navegar por URL ?page=N usando la URL REAL como base (preserva
        # store=so_acom_XXX y demas params que Sodimac agrego).
        navigated = False
        if total_pages and next_page_num <= total_pages and base_url:
            base = re.sub(r"([?&])page=\d+&?", r"\1", base_url).rstrip("?&")
            sep = "&" if "?" in base else "?"
            page_url = f"{base}{sep}page={next_page_num}"
            try:
                if await _safe_goto(page, page_url):
                    navigated = True
            except Exception:
                navigated = False

        if not navigated:
            # Fallback al boton next del DOM (compatibilidad)
            await page.evaluate("""() => document.querySelectorAll('[data-testid="overlay"], [class*="overlay"]').forEach(o => o.remove())""")
            next_btn = await page.query_selector(f'{SELECTORS["pagination_next"]}:not([disabled])')
            if not next_btn:
                break
            if new_in_page == 0 and not total_pages:
                break
            try:
                await next_btn.click(force=True, timeout=15000)
            except Exception:
                break

        page_num = next_page_num
        await page.wait_for_timeout(1500)
        if page_num > MAX_PAGES_PER_SUBCAT:
            result["truncated"] = True
            break

    return result


# ─────────────────────────────────────────  Store picker  ──────────────────

def pick_stores():
    """Devuelve la lista de tiendas seleccionadas por el usuario."""
    rm_stores = [s for s in ALL_STORES if s["region"] == "Metropolitana"]
    presets = [
        ("Solo Cerrillos (default — más rápido)", [s for s in ALL_STORES if s["id"] == "E522"]),
        (f"Todas RM ({len(rm_stores)} tiendas, ~2-3h)", rm_stores),
        (f"Todas Chile ({len(ALL_STORES)} tiendas, ~7h)", ALL_STORES),
        ("Personalizado (elegir manualmente)", None),
    ]
    choice = questionary.select(
        "¿Qué tiendas querés shoppear?",
        choices=[questionary.Choice(title=t, value=i) for i, (t, _) in enumerate(presets)],
        style=QSTYLE, instruction="(↑↓ para moverte, Enter para elegir)",
    ).ask()
    if choice is None:
        return None
    _, stores = presets[choice]
    if stores is not None:
        return stores
    # Custom: checkbox
    chs = [
        questionary.Choice(
            title=f"{s['id']}  {s['name']:<14}  ({s['region']} / {s['comuna']})",
            value=s,
            checked=(s["id"] == "E522"),
        )
        for s in ALL_STORES
    ]
    selected = questionary.checkbox(
        "Marcá las tiendas con [Espacio], confirmá con [Enter]:",
        choices=chs, style=QSTYLE,
    ).ask()
    return selected or []


# ─────────────────────────────────────────  Excel  ─────────────────────────

# Columnas finales del Excel (sin "Imagen" — esa se agrega siempre al final).
OUTPUT_COLS = [
    "Tienda", "Nombre Tienda", "Sección", "Subcategoría",
    "Vendedor", "Marca", "SKU", "Descripción Producto",
    "Precio Normal", "Precio Internet", "% Descuento",
    "Precio CMR", "Precio Mayorista", "Descuento Mayorista",
    "Todos los Precios", "URL",
]


def write_excel(rows, output_file, columns=None, *, with_images=False):
    """Escribe el Excel con columnas filtradas + URL truncado.

    columns: si se pasa, define el orden y subset de columnas. Si no, usa OUTPUT_COLS.
    with_images=False → 1 hoja "Datos" (sin fotos). with_images=True → 2 hojas:
    "Datos" (sin fotos) + "Con fotos" (mismos datos + screenshot embebido). Mismo
    formato que el MK7.
    """
    if not rows:
        return False
    from ._excel_utils import filter_and_reorder, write_two_sheets_df

    cols_to_use = columns if columns is not None else OUTPUT_COLS
    df = pd.DataFrame(rows)
    df = filter_and_reorder(df, cols_to_use)  # sin columna Imagen
    return write_two_sheets_df(df, rows, output_file, with_images=with_images)


# ─────────────────────────────────────────  UI  ────────────────────────────

def banner():
    console.print()
    console.print(Panel.fit(
        "[bold cyan]SODIMAC SELLER SCRAPER[/]\n"
        "[dim]Captura productos vendidos por Sodimac, por sección[/]",
        border_style="cyan", padding=(1, 4),
    ))
    console.print()


def section_summary(rows, section_name, output_file):
    t = Table(title=f"Resumen — {section_name}", box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    t.add_column("Métrica", style="white")
    t.add_column("Valor", style="bold green", justify="right")
    t.add_row("Filas totales", str(len(rows)))
    t.add_row("SKUs únicos", str(len({r["SKU"] for r in rows if r.get("SKU")})))
    t.add_row("Tiendas en el dataset", str(len({r["Tienda"] for r in rows if r.get("Tienda")})))
    t.add_row("Con Precio Mayorista", str(sum(1 for r in rows if r.get("Precio Mayorista"))))
    t.add_row("Con Precios Congelados", str(sum(1 for r in rows if r.get("Precios Congelados") == "Si")))
    t.add_row("Con % Descuento", str(sum(1 for r in rows if r.get("% Descuento"))))
    t.add_row("Con Precio CMR", str(sum(1 for r in rows if r.get("Precio CMR"))))
    t.add_row("Con Precio Normal (tachado)", str(sum(1 for r in rows if r.get("Precio Normal"))))
    console.print(t)
    console.print(f"\n[bold green]✓ Excel guardado en:[/] [cyan]{output_file}[/]")


# ─────────────────────────────────────────  Main  ──────────────────────────

async def main():
    banner()

    stores = pick_stores()
    if not stores:
        console.print("[yellow]No seleccionaste tiendas. Cancelado.[/]")
        return
    console.print(f"[green]✓[/] {len(stores)} tienda(s) seleccionada(s): " +
                  ", ".join(s["name"] for s in stores))

    async with Stealth().use_async(async_playwright()) as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900}, color_scheme="light",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # Set zone to first store to discover sections
        first = stores[0]
        with console.status(f"[cyan]Configurando zona {first['region']} / {first['comuna']}…[/]", spinner="dots"):
            ok = await set_zone_with_retry(page, first["region"], first["comuna"])
        if not ok:
            console.print(f"[red]No pude fijar zona en la primera tienda ({first['name']}). Abortando.[/]")
            await browser.close(); return
        console.print(f"[green]✓[/] Zona inicial: {first['name']} ({first['comuna']})")

        with console.status("[cyan]Descubriendo secciones del megamenu de Sodimac…[/]", spinner="dots"):
            sections = await discover_sections(page)
        if not sections:
            console.print("[red]No pude leer las secciones.[/]")
            await browser.close(); return
        console.print(f"[green]✓[/] {len(sections)} secciones detectadas")

        choices = [
            questionary.Choice(title=f"{n}  [dim]({len(subs)} subcat.)[/]", value=n)
            for n, subs in sections
        ]
        section_name = questionary.select(
            "¿Qué sección querés scrapear?",
            choices=choices, style=QSTYLE, instruction="(↑↓ para moverte, Enter para elegir)",
        ).ask()
        if not section_name:
            console.print("[yellow]Cancelado.[/]")
            await browser.close(); return
        subcats = next(subs for n, subs in sections if n == section_name)
        console.print(f"[green]✓[/] Sección: [bold]{section_name}[/] · {len(subcats)} subcategorías")

        all_rows = []
        non_sodimac = 0
        skipped_zone = []
        failed_subcats = []
        truncated_subcats = []

        run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
        partial = PartialWriter(run_id)
        console.print(f"[dim]Persistencia incremental: {partial.path}[/]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            store_task = progress.add_task(f"Tiendas", total=len(stores))
            cat_task = progress.add_task("Subcategorías", total=len(subcats))
            page_task = progress.add_task("Esperando…", total=None)

            for st_idx, store in enumerate(stores):
                progress.update(store_task, description=f"Tienda: {store['name']} ({store['comuna']})")
                # First store's zone already set; for the rest, change zone
                if st_idx > 0:
                    ok = await set_zone_with_retry(page, store["region"], store["comuna"])
                    if not ok:
                        skipped_zone.append(store["id"])
                        progress.advance(store_task)
                        continue

                seen_skus_in_store = set()
                progress.reset(cat_task, total=len(subcats))
                for sc_name, sc_url in subcats:
                    progress.update(cat_task, description=f"  └─ {sc_name}")
                    res = await scrape_subcat(page, section_name, sc_name, sc_url, progress, page_task, capture_screenshots=False, only_sodimac=True)
                    if res["failed"]:
                        failed_subcats.append((store["id"], sc_name))
                    if res["truncated"]:
                        truncated_subcats.append((store["id"], sc_name))
                    for r in res["rows"]:
                        vendedor = (r.get("Vendedor") or "").strip().upper()
                        if "SODIMAC" not in vendedor:
                            non_sodimac += 1
                            continue
                        sku = r.get("SKU")
                        if not sku or sku in seen_skus_in_store:
                            continue
                        seen_skus_in_store.add(sku)
                        # Two leading columns: store id + store name (e.g. E522 / Cerrillos).
                        r_copy = {"Tienda": store["id"], "Nombre Tienda": store["name"], **r}
                        all_rows.append(r_copy)
                        partial.write(r_copy)
                    progress.advance(cat_task)
                progress.advance(store_task)
            progress.remove_task(page_task)

        await browser.close()
        partial.close()

    console.print(f"\n[dim]Cards descartadas (no vendidas por Sodimac): {non_sodimac}[/]")
    if skipped_zone:
        console.print(f"[yellow]Tiendas saltadas por falla de zona: {', '.join(skipped_zone)}[/]")
    if failed_subcats:
        console.print(f"[yellow]Subcategorías que fallaron al cargar: {len(failed_subcats)}[/]")
        for store_id, sc in failed_subcats[:10]:
            console.print(f"   · {store_id} · {sc}")
    if truncated_subcats:
        console.print(f"[yellow]Subcategorías truncadas en {MAX_PAGES_PER_SUBCAT} pág: {len(truncated_subcats)}[/]")
        for store_id, sc in truncated_subcats[:10]:
            console.print(f"   · {store_id} · {sc}")

    if not all_rows:
        console.print("[yellow]No se encontraron productos vendidos por Sodimac.[/]")
        return

    unique_skus = len({r["SKU"] for r in all_rows if r.get("SKU")})
    console.print(f"[dim]{len(all_rows)} filas totales · {unique_skus} SKUs únicos en {len(stores)} tienda(s)[/]")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe = re.sub(r'[^\w\s-]', '', section_name).strip().replace(' ', '_')
    output = PROJECT_DIR / f"sodimac_{safe}_{timestamp}.xlsx"
    with console.status("[cyan]Escribiendo Excel con imágenes…[/]", spinner="dots"):
        write_excel(all_rows, str(output))

    section_summary(all_rows, section_name, output)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido por el usuario.[/]")

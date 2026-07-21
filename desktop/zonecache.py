# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Caché de zonas de Sodimac (cookies + árbol de categorías) — WIP, NO ACTIVO.

⚠️ Este módulo todavía NO está conectado a la app: se dejó para después por
tiempo. `orchestrators.run_fast` sigue haciendo el handshake normal. Para
activarlo hay que cablear get_jar/put_jar/get_tree en run_fast y llamar a
startup_check() al arrancar el servidor.

Estado: la validación por `priceGroupId` está escrita pero NO re-probada tras
corregir el falso positivo (buscar el nombre de la comuna en el HTML daba por
bueno un jar muerto, porque la zona por defecto ES Cerrillos). Antes de activarlo:
re-correr el test de ciclo (jar nuevo → cacheado → corrupto → limpiado).


POR QUÉ EXISTE
Fijar la zona cuesta ~17s por tienda (Playwright: warmup + set_zone). Con 42
tiendas son ~12 minutos antes de scrapear nada. Medido en vivo: el jar de
cookies **sigue sirviendo más de una hora** (sobrevive incluso a la expiración
del `__cf_bm` de Cloudflare a los 29 min), así que guardarlo entre corridas
elimina ese costo casi por completo.

NUNCA SE CONFÍA A CIEGAS
Un jar vencido no falla de forma ruidosa: devuelve precios de la zona por
defecto, que es peor que un error (datos silenciosamente equivocados). Por eso
antes de usarlo se **valida contra el servidor**: se pide una página con el jar
y se comprueba que venga contextualizada a la comuna esperada. Si no coincide,
se descarta la entrada y se rehace el handshake normal.

Verificado en vivo: la comuna aparece en el HTML servido y es específica de la
zona (jar Cerrillos → "Cerrillos" y cero menciones de "Puerto Montt", y al revés).

QUÉ SE GUARDA
Sólo cookies de sesión y URLs de categorías — datos del usuario, no código del
proyecto (el código sigue siendo efímero, ver desktop/shell.py).
"""
from __future__ import annotations

import json
import re
import ssl
import time
import unicodedata
import urllib.request
from pathlib import Path

CACHE_FILE = Path.home() / "Documents" / "Cruzer" / ".zonas.json"
# Tope conservador: se midió >60 min de vida real, pero la validación manda.
MAX_AGE = 45 * 60
PROBE_URL = "https://www.sodimac.cl/sodimac-cl/lista/cat6930448/camping"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _norm(s: str) -> str:
    """Minúsculas sin acentos (las comunas aparecen con y sin tilde)."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def jar_price_group(jar: str) -> str | None:
    """El `priceGroupId` que trae el jar (lo fija set_zone en el navegador)."""
    m = re.search(r"priceGroupId=(\d+)", jar or "")
    return m.group(1) if m else None


def _server_price_group(jar: str, *, timeout=25) -> str | None:
    """El `priceGroupId` que el SERVIDOR aplica al responder con ese jar.

    Ésta es la verdad: las cookies pueden decir una cosa y el backend responder
    con la zona por defecto. Verificado en vivo: jar de Cerrillos → 96, jar de
    Puerto Montt → 41, jar inválido o sin cookies → 96 (el default).
    """
    try:
        req = urllib.request.Request(
            PROBE_URL, headers={"User-Agent": _UA, "Cookie": jar, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    mm = re.search(r'"priceGroupId"\s*:\s*"?(\d+)"?', m.group(1))
    return mm.group(1) if mm else None


def _load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"jars": {}, "trees": {}}


def _save(data: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def validate(jar: str, expected_pg: str | None, *, timeout=25) -> bool:
    """True si el servidor sigue aplicando la MISMA zona que cuando se guardó.

    No sirve buscar el nombre de la comuna en el HTML: con un jar inválido
    Sodimac responde con la zona por defecto (priceGroupId 96 = Cerrillos), que
    menciona igual varias comunas → daba falsos positivos. Se compara el
    `priceGroupId` que el servidor aplica contra el capturado al cachear.

    Nota: para la zona por defecto (96) un jar muerto es indistinguible de uno
    vivo, pero es inofensivo — los datos que devuelve son los mismos.
    """
    if not jar or not expected_pg:
        return False
    return _server_price_group(jar, timeout=timeout) == str(expected_pg)


def get_jar(store: dict) -> str | None:
    """Jar cacheado y VALIDADO para esa tienda, o None. Si no sirve, lo borra."""
    data = _load()
    e = (data.get("jars") or {}).get(store["id"])
    if not e:
        return None
    if time.time() - e.get("ts", 0) > MAX_AGE:
        drop_jar(store["id"])
        return None
    if not validate(e.get("jar", ""), e.get("pg")):
        drop_jar(store["id"])
        return None
    return e["jar"]


def put_jar(store: dict, jar: str) -> None:
    """Guarda el jar junto al priceGroupId que trae (huella de la zona)."""
    pg = jar_price_group(jar)
    if not jar or not pg:
        return
    data = _load()
    data.setdefault("jars", {})[store["id"]] = {
        "jar": jar, "ts": time.time(), "comuna": store["comuna"], "pg": pg}
    _save(data)


def drop_jar(store_id: str) -> None:
    data = _load()
    if (data.get("jars") or {}).pop(store_id, None) is not None:
        _save(data)


def get_tree(scheme: str = "full"):
    """Árbol de categorías cacheado (no depende de la zona). None si venció."""
    data = _load()
    e = (data.get("trees") or {}).get(scheme)
    if not e or time.time() - e.get("ts", 0) > 24 * 3600:
        return None
    return [(s["section"], [(x["name"], x["url"]) for x in s["subcats"]])
            for s in e.get("tree", [])] or None


def put_tree(tree, scheme: str = "full") -> None:
    data = _load()
    data.setdefault("trees", {})[scheme] = {
        "ts": time.time(),
        "tree": [{"section": sec, "subcats": [{"name": n, "url": u} for n, u in subs]}
                 for sec, subs in tree]}
    _save(data)


def startup_check(log=print) -> dict:
    """Test inicial al arrancar: valida los jars guardados y limpia los que no sirven.

    Devuelve {"ok": n, "purgados": n}. Barato: 1 request por tienda cacheada.
    """
    data = _load()
    jars = dict(data.get("jars") or {})
    if not jars:
        return {"ok": 0, "purgados": 0}
    ok = purged = 0
    for sid, e in jars.items():
        vencido = time.time() - e.get("ts", 0) > MAX_AGE
        if vencido or not validate(e.get("jar", ""), e.get("pg")):
            drop_jar(sid)
            purged += 1
        else:
            ok += 1
    if purged:
        log(f"Zonas en caché: {ok} válidas, {purged} vencidas (se limpiaron).")
    elif ok:
        log(f"Zonas en caché: {ok} válidas (se saltan {ok * 17}s de handshake).")
    return {"ok": ok, "purgados": purged}

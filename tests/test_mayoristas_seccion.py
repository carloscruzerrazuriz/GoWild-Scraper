# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
"""Prueba en vivo: crawl COMPLETO por sección (browserless) + filtro mayorista.

    python3 test_mayoristas_seccion.py [max_subcats]   # default 8 (demo)
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # raíz del repo
import time

from engines import mayoristas_fast as mf
from engines import maestra_sodimac as _ss

STORE = {"id": "E522", "name": "Cerrillos", "region": "Metropolitana", "comuna": "Cerrillos"}


async def main():
    max_subcats = int(sys.argv[1]) if len(sys.argv) > 1 else 8

    print(">>> [1] open_session: navegador 1 vez (warmup + set_zone + árbol) ...")
    t0 = time.time()
    cookie, tree = await mf.open_session(STORE, headless=True)
    n_sub = sum(len(s) for _, s in tree)
    print(f"    cookie {'OK' if cookie else 'FALLÓ'}, {len(tree)} secciones / {n_sub} subcats  ({time.time()-t0:.1f}s)")
    if not cookie:
        return

    print(f">>> [2] Barriendo {max_subcats} subcats por HTTP, filtrando mayoristas ...")
    t1 = time.time()
    kept_total = {"k": 0, "s": 0}

    WHOLESALE = "--all" not in sys.argv  # por defecto solo mayoristas; --all = sin filtrar

    def _subcat_cb(i, total, sec, name, kept, scanned, status=None):
        kept_total["k"] += kept
        kept_total["s"] += scanned
        st = status or {}
        exp = st.get("expected")
        flag = "  ⚠️ INCOMPLETA" if st.get("incomplete") else ("  ~short" if st.get("short") else "")
        ok = "" if exp is None else f"  (declara {exp})"
        print(f"    [{i}/{max_subcats}] {sec[:16]:<16} / {name[:22]:<22}  escaneados={scanned:>4}{ok}  guardados={kept:>3}{flag}")

    report = []
    rows = mf.scrape_all_wholesale(cookie, tree, STORE, wholesale_only=WHOLESALE,
                                   only_sodimac=True, subcat_cb=_subcat_cb,
                                   max_subcats=max_subcats, report=report)
    print(f"\n    Modo: {'SOLO MAYORISTAS' if WHOLESALE else 'TODO EL CATÁLOGO (sin filtrar)'}")
    if report:
        print(f"    ⚠️ {len(report)} categoría(s) INCOMPLETAS tras reintento (error de fetch / MAX_PAGES):")
        for r in report:
            print(f"       {r['section']} / {r['subcat']}: {r['scanned']}/{r['expected']} ({r['reason']})")
    else:
        print("    ✅ Ninguna categoría incompleta (todas llegaron a fin natural de páginas)")
    dt = time.time() - t1
    print(f"\n    escaneados={kept_total['s']} productos  ->  mayoristas={len(rows)}  en {dt:.1f}s")
    if kept_total["s"]:
        print(f"    ritmo: {kept_total['s']/max(dt,1):.0f} productos/s escaneados; "
              f"{dt/max_subcats:.1f}s por subcat")
        print(f"    proyección full-catálogo ({n_sub} subcats): ~{dt/max_subcats*n_sub/60:.1f} min por zona")

    print("\n>>> Muestras (mayoristas encontrados):")
    for r in rows[:10]:
        print(f"    {r['SKU']:>10}  int={r['Precio Internet']:>11}  may={r['Precio Mayorista']:>11}"
              f"  {r['Descuento Mayorista']:>10}  {r['Sección'][:12]:<12} {r['Descripción Producto'][:28]}")

    if rows:
        out = "sodimac_mayoristas_SECCION_demo.xlsx"
        _ss.write_excel(rows, out, columns=mf.OUTPUT_COLS, with_images=False)
        print(f"\n>>> Excel: {out}")
    print(f"TIEMPO TOTAL: {time.time()-t0:.1f}s")


asyncio.run(main())

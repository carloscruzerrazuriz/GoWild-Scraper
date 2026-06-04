# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
"""Test en vivo del engine pcf_seccion contra la API real de PCFactory.

Corre fuera de Colab (sólo urllib stdlib + openpyxl). Verifica:
  1. discover_sections() trae el árbol.
  2. scrape_section() pagina y arma rows con precios reales.
  3. write_excel() genera el .xlsx con la estética del proyecto.

Uso:  python3 test_pcf_seccion.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines import pcf_seccion as eng  # noqa: E402


def main():
    print("1) discover_sections()…")
    secciones = eng.discover_sections(progress_cb=lambda ev: print(f"   {ev}"))
    print(f"   → {len(secciones)} familias")
    for nombre, subs in secciones[:3]:
        print(f"   · {nombre}: {len(subs)} subcategorías "
              f"(ej: {subs[0] if subs else '—'})")

    # Elegimos una subcategoría chica para no bajar miles de filas en el test.
    # Procesadores → CPU Intel (id 1142, ~12 productos).
    target = ("Procesadores", 1142)
    print(f"\n2) scrape_section([{target}], limit=20)…")
    seen = []
    rows = eng.scrape_section(
        [target],
        on_row=lambda r: seen.append(r),
        progress_cb=lambda ev: print(f"   evento {ev}"),
        limit=20,
    )
    print(f"   → {len(rows)} filas")
    assert rows, "No se obtuvieron filas"
    assert len(seen) == len(rows), "on_row no se llamó por cada fila"

    sample = rows[0]
    print("\n   Muestra de fila:")
    for k in ("Tienda", "Subcategoría", "Marca", "SKU", "Descripción Producto",
              "Precio Efectivo", "Precio Normal", "Precio Referencia",
              "% Descuento", "Stock", "Promoción", "URL"):
        print(f"     {k:22}: {sample.get(k)}")

    # Sanidad de datos.
    assert sample["Tienda"] == "PCFactory"
    assert sample["SKU"], "SKU vacío"
    assert sample["Descripción Producto"], "Nombre vacío"
    assert isinstance(sample["Precio Efectivo"], (int, float)), "Precio no numérico"
    assert sample["URL"].startswith("https://www.pcfactory.cl/producto/")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_test_pcfactory_seccion.xlsx")
    print(f"\n3) write_excel(...) → {out}")
    eng.write_excel(rows, out)
    assert os.path.exists(out) and os.path.getsize(out) > 0, "Excel vacío"
    print(f"   → OK ({os.path.getsize(out)} bytes)")

    print("\n✅ TODO OK")


if __name__ == "__main__":
    main()

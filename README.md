# GoWild-Scraper

Scrapers de precios y catálogos para **Sodimac · Falabella · Construmart**, distribuidos como notebooks Colab delgados con auto-actualización desde este repo.

## Arquitectura

```
GoWild-Scraper/
├── notebooks/        ← .ipynb DELGADOS (3 celdas) — esto es lo que el usuario abre en Colab
│   ├── MK7_Buscador_SKUs.ipynb
│   ├── Maestra_Seccion.ipynb
│   └── Precios_Mayoristas.ipynb
│
├── launchers/        ← UI ipywidgets + lógica de cada herramienta
│   ├── __init__.py   ← función boot(tool_name)
│   ├── mk7.py
│   ├── maestra.py
│   └── mayoristas.py
│
├── engines/          ← motores de scraping (Sodimac, Falabella, Construmart, Maestras)
│   ├── sodimac_engine.py
│   ├── falabella_engine.py
│   ├── construmart_engine.py
│   ├── maestra_sodimac.py
│   ├── maestra_falabella.py
│   └── maestra_construmart.py
│
└── version.json      ← versión + launcher_schema
```

## Cómo funciona el auto-update

Cada notebook en `notebooks/` tiene 3 celdas:

1. **Markdown** — título e instrucciones.
2. **Bootstrap** — `git clone --depth 1` (o `pull`) de este repo y agrega `/content/gowild` al `sys.path`. Valida que `launcher_schema` del repo coincida con el que el notebook espera.
3. **Boot** — `from launchers import boot; boot("mk7")` (o `maestra`/`mayoristas`).

**El resultado:** el usuario descarga el `.ipynb` **una sola vez**. Cada Run All trae los últimos engines, UI y fixes del repo. Solo se requiere un nuevo `.ipynb` si cambia el `launcher_schema` (raro).

## Links de Colab para distribución

Pega estos links a tus usuarios — abren el `.ipynb` más reciente del repo:

- 🏷️ MK7 Buscador SKUs:
  `https://colab.research.google.com/github/carloscruzerrazuriz/GoWild-Scraper/blob/main/notebooks/MK7_Buscador_SKUs.ipynb`
- 🗂️ Maestra Sección:
  `https://colab.research.google.com/github/carloscruzerrazuriz/GoWild-Scraper/blob/main/notebooks/Maestra_Seccion.ipynb`
- 💰 Precios Mayoristas:
  `https://colab.research.google.com/github/carloscruzerrazuriz/GoWild-Scraper/blob/main/notebooks/Precios_Mayoristas.ipynb`

## Para el mantenedor

- Bug fix en un engine → editar `engines/<x>.py` → `git push`. Próximo run de cualquier usuario ya lo tiene.
- Cambio en la UI de un launcher → editar `launchers/<x>.py` → `git push`. Igual.
- Nuevo tool → crear `launchers/<nuevo>.py`, registrar en `launchers/__init__.py`, crear `notebooks/Nuevo.ipynb` (con `boot("nuevo")`), `git push`. Solo el `.ipynb` nuevo se distribuye a usuarios.
- Cambio incompatible del schema (raro) → bump `launcher_schema` en `version.json`. Los notebooks viejos detectan la diferencia y avisan al usuario que pida el nuevo `.ipynb`.

## Dependencias

Colab cloud trae casi todo. Si un usuario corre fuera de Colab necesita:
```
pip install playwright playwright-stealth nest_asyncio ipywidgets pandas openpyxl questionary rich requests
playwright install chromium
```

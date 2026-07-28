# 🗺️ Mapa del proyecto — GoWild Scraper

Guía simple de qué es cada carpeta y archivo. (El detalle técnico completo está en
`../docs/contexto-maestro.md`; esto es la versión para orientarse rápido.)

## La idea en una línea
Un repositorio con **motores de scraping** de retailers chilenos. Se usa de dos formas:
- **Colab** (notebooks que se auto-actualizan desde acá), y
- **Cruzer**, la app de escritorio (Windows/Mac) que corre los mismos motores en tu PC.

Cuando se hace `git push`, **todos** (Colab y Cruzer) quedan actualizados solos.

---

## Las carpetas

### `engines/` — el cerebro (la lógica de scraping, sin interfaz)
Un archivo por "motor". Agrupados por retailer:

| Grupo | Archivos | Qué hacen |
|---|---|---|
| **Compartido** | `_zone_sodimac`, `_checkpoints`, `_excel_utils`, `_locales_easy`, `_maestra_post`, `__init__` | Piezas que usan varios motores: zona Sodimac, reanudación, armado de Excel, mapa Región/Zona, subida a la Maestra. |
| **Sodimac** | `sodimac_engine` (MK7), `maestra_sodimac` (Catálogo), `mayoristas_fast` (Catálogo Express), `ferni_sodimac` + `ferni_maestra_sodimac` (Puertas) | Los motores de Sodimac. |
| **Falabella** | `falabella_engine`, `maestra_falabella` | Buscar por SKU y Catálogo de Falabella. |
| **Construmart** | `construmart_engine`, `maestra_construmart` | Ídem Construmart. |
| **Competidores** | `comp_base` + `comp_*` (PuntoMaestro, Ferrobal, Imperial, Construplaza, DVP, Yolito, Oviedo, Prodalam) | 10 retailers de la competencia (herramienta de Colab). |
| **PCFactory** | `pcf_base`, `pcf_seccion`, `pcf_detalle` | Scraper de pcfactory.cl (Colab, en inglés). |
| **Portal Inmobiliario** | `portalinmobiliario` | Avisos de MercadoLibre inmobiliario (pausado). |

### `launchers/` — las interfaces de **Colab** (ipywidgets)
Cada archivo arma la UI de una herramienta en el notebook y llama a su motor:
`mk7`, `maestra`, `mayoristas`, `ferni*`, `competidores`, `pcfactory*`, `portalinmobiliario`.

### `desktop/` — la app **Cruzer** (Windows/Mac)
| Archivo/carpeta | Qué es |
|---|---|
| `shell.py` | El arranque (esto se empaqueta en el `.exe`/`.app`): baja el código de GitHub, muestra el splash, abre la ventana. |
| `server.py` | El servidor local (sirve la UI + los endpoints). |
| `orchestrators.py` | El "puente": conecta la UI con los motores de `engines/`. |
| `ui/` | La interfaz web (HTML/CSS/JS) que ves en la ventana. |
| `build/` | Las recetas para compilar (`cruzer.spec` Windows, `cruzer-mac.spec` Mac, íconos). |
| `dev.py` | Arranque de desarrollo (sin bajar de GitHub). |

### `notebooks/` — los `.ipynb` **delgados** de Colab
Archivos livianos (3 celdas) que el equipo abre en Colab; toda la lógica llega de `engines/`.

### `apps_script/` — código de **Google Apps Script**
`Maestra_Sodimac.gs`: el Web App que recibe los scrapes y arma la Maestra consolidada en un Google Sheet.

### `tests/` — pruebas en vivo
Scripts para verificar motores contra los sitios reales.

---

## Archivos sueltos de la raíz
- `version.json` — versión del proyecto (para los Colab).
- `requirements.txt` — librerías que se instalan.
- `README.md` — guía de mantenimiento + links de distribución.
- `LICENSE` — licencia propietaria.
- `CONTEXT.md` — nota histórica.

---

## ¿Dónde toco si quiero cambiar…?
- **…lo que hace un scraper** → `engines/<el motor>`.
- **…cómo se ve la app de escritorio** → `desktop/ui/`.
- **…un texto/botón en Colab** → `launchers/<la herramienta>`.
- **…y que llegue a todos** → `git push` (Colab y Cruzer se actualizan solos; el `.exe`/`.app` sólo se recompila si cambia `shell.py`, las dependencias o el ícono).

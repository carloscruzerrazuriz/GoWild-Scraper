# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""GoWild-Scraper engines package.

Side-effect: garantiza que las librerías del SO que Chromium (Playwright) necesita
estén instaladas — algunas distribuciones de Colab no las traen por default.
Idempotente: solo ejecuta apt-get si detecta que falta libatk (el primero que
suele faltar). Marca con un sentinel para no repetir en runs futuros.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SENTINEL = Path("/tmp/.gowild_playwright_deps_ok")
_LIB_CHECK = "/usr/lib/x86_64-linux-gnu/libatk-1.0.so.0"


def _ensure_playwright_system_deps() -> None:
    if _SENTINEL.exists():
        return
    if os.path.exists(_LIB_CHECK):
        _SENTINEL.touch()
        return
    # Falta libatk → llamar a playwright install-deps (instala todo lo que Chromium pide vía apt).
    print("🔧 Instalando librerías del sistema para Chromium (~20s, una sola vez)…")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0:
            _SENTINEL.touch()
            print("   ✅ Librerías de sistema instaladas.")
        else:
            # Fallback: intentar apt-get directo de los libs más comunes que pide Chromium
            print(f"   ⚠️ playwright install-deps no completó (rc={result.returncode}). Probando apt-get directo…")
            subprocess.run(
                ["apt-get", "install", "-y", "libatk-1.0-0", "libatk-bridge-2.0-0", "libcups2",
                 "libxkbcommon0", "libxcomposite1", "libxdamage1", "libxfixes3", "libxrandr2",
                 "libgbm1", "libpango-1.0-0", "libcairo2", "libasound2"],
                capture_output=True, text=True, timeout=120,
            )
            if os.path.exists(_LIB_CHECK):
                _SENTINEL.touch()
                print("   ✅ Librerías instaladas vía apt-get fallback.")
    except Exception as e:
        print(f"   ⚠️ No se pudo instalar deps automáticamente: {e}")
        print("   Si el scraper falla con 'libatk', corre manualmente en una celda:")
        print("     !apt-get install -y libatk-1.0-0 libcups2 libxkbcommon0 libxcomposite1")


# Se ejecuta al importar `engines` (los launchers hacen `from engines import …`).
_ensure_playwright_system_deps()

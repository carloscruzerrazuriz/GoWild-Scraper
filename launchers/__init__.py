# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""GoWild-Scraper launcher dispatcher.

Each notebook calls `boot("<tool_name>")` to launch its UI. The launcher modules
are kept in this package; new tools = new modules. The notebooks themselves are
thin shells (bootstrap + boot() call) so 99% of changes propagate via `git pull`
without users needing a new .ipynb.
"""
from __future__ import annotations

LAUNCHER_SCHEMA = "1.0"

_TOOLS = {
    "mk7":          "launchers.mk7",
    "maestra":      "launchers.maestra",
    "mayoristas":   "launchers.mayoristas",
    "ferni":        "launchers.ferni",
    "competidores": "launchers.competidores",
    "pcfactory":    "launchers.pcfactory",
}


def boot(tool: str) -> None:
    """Entry point invoked from each notebook's last cell.

    Force-reloads the launcher and any cached engines/* modules so that a fresh
    `git pull` always propagates to the running kernel (without needing a kernel
    restart from the user).
    """
    import importlib
    import sys

    if tool not in _TOOLS:
        available = ", ".join(sorted(_TOOLS))
        raise ValueError(f"Tool desconocido: {tool!r}. Disponibles: {available}")

    # Drop any cached launchers.* and engines.* modules so import re-reads from disk.
    for cached in [name for name in list(sys.modules)
                   if name.startswith("launchers.") or name.startswith("engines.")]:
        del sys.modules[cached]

    mod = importlib.import_module(_TOOLS[tool])
    if not hasattr(mod, "run"):
        raise RuntimeError(f"El launcher {_TOOLS[tool]} no expone run()")
    mod.run()

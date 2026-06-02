# GoWild-Scraper: IP Protection Context

**Date:** 2026-06-02  
**Goal:** Protect intellectual property by preventing users from reading/stealing the source code while maintaining full functionality in Colab notebooks.

---

## Problem Statement

- **Current State:** Repository is `public` with source code visible
- **Concern:** Users can view and steal the scraping engine logic (sodimac, falabella, construmart, maestra, ferni)
- **Critical Issue:** Even with bytecode compilation, users can browse files in Colab's file explorer and decompile `.pyc` files
- **Objective:** Distribute Colab notebooks that work perfectly, but with code that is completely inaccessible for inspection
- **Constraint:** Must maintain auto-update architecture (notebooks pull latest code from repo via git)

---

## Repository Structure Overview

```
GoWild-Scraper/
├── notebooks/                    ← User-facing Colab files (.ipynb)
│   ├── MK7_Buscador_SKUs.ipynb
│   ├── Maestra_Seccion.ipynb
│   ├── Precios_Mayoristas.ipynb
│   └── Buscador_Puertas_Sodimac.ipynb (Ferni)
│
├── launchers/                    ← UI + logic entry points
│   ├── __init__.py (boot function)
│   ├── mk7.py
│   ├── maestra.py
│   ├── mayoristas.py
│   ├── ferni.py
│   ├── ferni_sku.py
│   └── ferni_maestra.py
│
├── engines/                      ← SENSITIVE: Scraping logic
│   ├── sodimac_engine.py         ← IP to protect
│   ├── falabella_engine.py       ← IP to protect
│   ├── construmart_engine.py     ← IP to protect
│   ├── maestra_sodimac.py
│   ├── maestra_falabella.py
│   ├── maestra_construmart.py
│   ├── ferni_sodimac.py
│   └── ferni_maestra_sodimac.py
│
└── version.json                  ← Launcher schema version control
```

---

## Options Evaluated

### **Option 1: Compiled Python (.pyc files)** ❌ INSUFFICIENT ALONE
- **How:** Convert `.py` to compiled bytecode (`.pyc`)
- **Protection Level:** LOW-MEDIUM - Users can still decompile with effort
- **Critical Flaw:** In Colab, users can browse files in the left panel and download `.pyc` files to decompile locally using `uncompyle6`
- **Verdict:** NOT RECOMMENDED as sole solution
- **Issue:** Files are visible in Colab file explorer after git clone

### **Option 2: Obfuscation (PyArmor/Cython)** ❌ INSUFFICIENT ALONE
- **How:** Scramble variable names, strings, logic flow
- **Protection Level:** MEDIUM - Harder to read, but decompilable
- **Critical Flaw:** Source still visible in Colab; users can download and reverse-engineer
- **Verdict:** NOT RECOMMENDED

### **Option 3: Encryption at Runtime** ❌ NOT VIABLE
- **How:** Encrypt code, decrypt in Colab before execution
- **Protection Level:** LOW - Key must be in code somewhere
- **Critical Flaw:** Key can be extracted from code; not practical for Colab
- **Verdict:** NOT RECOMMENDED

### **Option 4: Private Repository** ❌ POOR UX
- **How:** Make repo private, distribute via GitHub authentication
- **Protection Level:** MEDIUM - Code hidden from unauthorized users
- **Trade-offs:** Users need GitHub tokens, breaks seamless Colab distribution
- **Verdict:** NOT RECOMMENDED - Complicates user experience significantly

### **Option 5: Two-Repository Approach + Sparse Checkout** ⭐ RECOMMENDED
- **How:** 
  - Keep **private repo** with full source code (development only)
  - Maintain **public repo** with ONLY compiled `.pyc` files (distribution)
  - Users clone public repo, see no source files, only compiled modules
  - Notebooks use sparse-checkout to pull only compiled code
- **Protection Level:** MAXIMUM - Source code never in public repo; users can't inspect or decompile what they don't have
- **Trade-offs:** Requires managing two repositories (but worth it)
- **Why This Works:**
  - ✅ Users see no source files in Colab file explorer
  - ✅ No `.pyc` files to decompile (architecture issue solved)
  - ✅ Auto-updates preserved (pull latest compiled modules)
  - ✅ Maximum IP protection (source stays private)
  - ✅ Industry-standard approach (used by commercial software)

---

## CHOSEN SOLUTION: Two-Repository Approach

### **Architecture Overview**

**Repository 1: PRIVATE (Development Only)**
```
GoWild-Scraper-Private/  
├── notebooks/           ← Source notebooks (development)
├── launchers/           ← Source code (SENSITIVE)
├── engines/             ← Source code (SENSITIVE)
├── version.json
├── build.py             ← Compilation script
└── .github/workflows/   ← Build automation
```

**Repository 2: PUBLIC (Distribution)**
```
GoWild-Scraper/         ← Users clone this
├── notebooks/           ← Distribution notebooks (minimal)
├── launchers/           ← Only .pyc compiled files
│   ├── __pycache__/
│   │   ├── mk7.cpython-310.pyc
│   │   ├── maestra.cpython-310.pyc
│   │   └── ... (compiled modules only)
│   └── __init__.py      ← ONLY bootstrap init
│
├── engines/             ← Only .pyc compiled files
│   ├── __pycache__/
│   │   ├── sodimac_engine.cpython-310.pyc
│   │   ├── falabella_engine.cpython-310.pyc
│   │   └── ... (compiled modules only)
│
├── version.json
└── README.md
```

### **Why This Works**

1. **Source code is NEVER in public repo** - Only compiled bytecode
2. **Users can't inspect files** - Colab file explorer shows only `.pyc` (unreadable)
3. **Users can't decompile** - No compiled files to extract (they stay in private repo)
4. **Auto-updates work** - Public repo always has latest compiled code
5. **Maximum security** - IP is completely protected

---

## Implementation Steps

### **Step 1: Create Two Repositories**

**Repository 1: Private Development Repo**
```bash
# Clone your EXISTING repo and make a backup for private development
git clone https://github.com/carloscruzerrazuriz/GoWild-Scraper.git GoWild-Scraper-Private
cd GoWild-Scraper-Private

# Push to new private repo (you create it in GitHub settings first)
git remote set-url origin https://github.com/carloscruzerrazuriz/GoWild-Scraper-Private.git
git push -u origin main
```

**Repository 2: Public Distribution Repo**
- Keep your existing `GoWild-Scraper` public
- This is where compiled files go (created automatically)

### **Step 2: Create Build Script in Private Repo (`build.py`)**

```python
import py_compile
import os
import shutil
from pathlib import Path

def build_compiled_version():
    """
    Compile Python files to bytecode and prepare for public distribution.
    Run this in the PRIVATE repo before pushing to public repo.
    """
    
    dirs_to_compile = ['engines', 'launchers']
    
    for directory in dirs_to_compile:
        if not os.path.exists(directory):
            continue
            
        print(f"Compiling {directory}/...")
        
        # Create __pycache__ for each directory
        pycache_dir = Path(directory) / '__pycache__'
        pycache_dir.mkdir(exist_ok=True)
        
        for py_file in Path(directory).glob('*.py'):
            # Keep __init__.py as source (needed for imports)
            if py_file.name == '__init__.py':
                print(f"  → {py_file.name} (kept as source)")
                continue
            
            try:
                # Compile to .pyc
                py_compile.compile(str(py_file), doraise=True)
                print(f"  ✓ {py_file.name} compiled")
                
            except py_compile.PyCompileError as e:
                print(f"  ✗ {py_file.name}: {e}")

if __name__ == "__main__":
    build_compiled_version()
    print("\n✅ Build complete! Compiled files in __pycache__/")
```

### **Step 3: Create GitHub Actions Workflow in Private Repo (`.github/workflows/build-and-publish.yml`)**

```yaml
name: Build and Publish Compiled Version

on:
  push:
    branches: [main]
    paths:
      - 'engines/**'
      - 'launchers/**'
      - 'build.py'

jobs:
  compile:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Run build script
      run: python build.py
    
    - name: Verify compiled files
      run: |
        echo "=== Compiled files in engines/:"
        find engines/__pycache__ -name "*.pyc" 2>/dev/null || echo "None yet"
        echo "=== Compiled files in launchers/:"
        find launchers/__pycache__ -name "*.pyc" 2>/dev/null || echo "None yet"
    
    - name: Push compiled files to PUBLIC repo
      env:
        PUBLIC_REPO_TOKEN: ${{ secrets.PUBLIC_REPO_PUSH_TOKEN }}
      run: |
        # Clone the PUBLIC repo
        git clone --depth 1 \
          https://x-access-token:${{ env.PUBLIC_REPO_TOKEN }}@github.com/carloscruzerrazuriz/GoWild-Scraper.git \
          public_repo
        
        # Copy compiled files to public repo
        cp -r engines/__pycache__ public_repo/engines/
        cp -r launchers/__pycache__ public_repo/launchers/
        cp engines/__init__.py public_repo/engines/ 2>/dev/null || true
        cp launchers/__init__.py public_repo/launchers/ 2>/dev/null || true
        
        # Copy notebooks
        cp -r notebooks/*.ipynb public_repo/notebooks/
        cp version.json public_repo/
        
        # Commit and push
        cd public_repo
        git config user.email "action@github.com"
        git config user.name "GitHub Action (Build)"
        git add -A
        git commit -m "🔐 Auto-build: Publish compiled bytecode version [skip ci]" || echo "No changes"
        git push origin main
```

**Note:** You need to:
1. Create a GitHub Personal Access Token for the public repo
2. Add it as a secret `PUBLIC_REPO_PUSH_TOKEN` in the private repo settings

### **Step 4: Update Colab Bootstrap Cell to Use Sparse Checkout**

In your notebooks' **Cell #2 (Bootstrap)**, replace the git clone with sparse checkout:

```python
# === BOOTSTRAP CELL - Auto-update from compiled repo ===

import subprocess
import sys
import os

REPO_URL = "https://github.com/carloscruzerrazuriz/GoWild-Scraper.git"
LOCAL_DIR = "/content/gowild"

print("📥 Loading compiled modules (source code protected)...")

# Clone with sparse checkout - only get compiled code
if not os.path.exists(LOCAL_DIR):
    subprocess.run([
        "git", "clone", 
        "--depth", "1",
        "--sparse",
        REPO_URL, 
        LOCAL_DIR
    ], check=True, capture_output=True)
    
    os.chdir(LOCAL_DIR)
    
    # Sparse checkout: only compiled __pycache__ directories
    subprocess.run([
        "git", "sparse-checkout", "set",
        "launchers",
        "engines",
        "version.json"
    ], check=True, capture_output=True)
else:
    # Update existing
    os.chdir(LOCAL_DIR)
    subprocess.run(["git", "pull", "--depth", "1"], check=True, capture_output=True)

# Add to path
if LOCAL_DIR not in sys.path:
    sys.path.insert(0, LOCAL_DIR)

print("✅ Compiled modules loaded! (IP protected)")
```

### **Step 5: Configure .gitignore in Public Repo**

```gitignore
# Source files - NEVER committed to public repo
*.py
!__init__.py
!notebooks/*.ipynb

# Keep compiled bytecode
!**/__pycache__/
!**/*.pyc

# Standard Python ignores
__pycache__/
*.so
.pytest_cache/
.Python
env/
venv/
```

### **Step 6: Update README.md**

Add a section in your public repo README:

```markdown
## ⚠️ About This Repository

This repository contains **compiled bytecode distributions** of the GoWild-Scraper tools.

- **Source code is not included** for intellectual property protection
- **All functionality is preserved** - works exactly the same as source code
- **Code cannot be inspected or modified** by end users
- **Auto-updates are automatic** - users get latest compiled version on each run

This is a standard security practice used by commercial software providers.
```

---

## Development Workflow

### **In Your PRIVATE Repo:**

```bash
# 1. Make changes to source code
# - Edit engines/sodimac_engine.py
# - Edit launchers/mk7.py
# - etc.

# 2. Commit locally
git add .
git commit -m "Fix: sodimac scraper selectors"

# 3. Push to private repo
git push origin main

# 4. GitHub Actions automatically:
#    - Runs build.py (compiles .py to .pyc)
#    - Pushes compiled files to PUBLIC repo
```

### **In the PUBLIC Repo (Auto-Updated):**

```
Users see:
├── notebooks/                    ← Can read/modify
├── launchers/__pycache__/       ← Compiled only (unreadable)
├── engines/__pycache__/         ← Compiled only (unreadable)
└── version.json                 ← Metadata

Users cannot see:
❌ launchers/mk7.py
❌ launchers/maestra.py
❌ engines/sodimac_engine.py
❌ (all source .py files)
```

---

## How It Works for Users

1. **User clicks Colab link** → Opens notebook from public repo
2. **Notebook runs bootstrap cell** → Git clone of public repo (only compiled files)
3. **Sparse checkout pulls** → Only `launchers/__pycache__/` and `engines/__pycache__/`
4. **Python imports modules** → `from launchers import boot` loads compiled bytecode
5. **Code executes normally** → User gets full functionality
6. **Code is completely inaccessible** → No source files exist in public repo to inspect

---

## Security Comparison

| Aspect | Public Source | Bytecode Only | Two-Repo Solution |
|--------|---------------|---------------|-------------------|
| Source code visible? | ✅ YES | ✅ YES (in .pyc) | ❌ NO |
| Users can inspect? | ✅ YES | ⚠️ DIFFICULT | ❌ NO |
| Can be decompiled? | ✅ EASILY | ⚠️ POSSIBLE | ❌ FILES DON'T EXIST |
| IP Protected? | ❌ NO | ⚠️ PARTIAL | ✅ MAXIMUM |
| Complexity? | 🟢 Low | 🟡 Medium | 🟠 High |
| Recommended? | ❌ | ❌ | ✅ YES |

---

## Current Development Environment

- **Editor:** Antigravity + Claude (Aider)
- **Private Repository:** `carloscruzerrazuriz/GoWild-Scraper-Private` (to create)
- **Public Repository:** `carloscruzerrazuriz/GoWild-Scraper` (exists, will be updated)
- **Visibility:** Private (dev) → Public (distribution)
- **Language:** Python
- **Automation:** GitHub Actions

---

## Setup Checklist

- [ ] Create private repository: `GoWild-Scraper-Private`
- [ ] Push existing code to private repo
- [ ] Create `build.py` in private repo
- [ ] Create `.github/workflows/build-and-publish.yml` in private repo
- [ ] Generate GitHub Personal Access Token for public repo
- [ ] Add `PUBLIC_REPO_PUSH_TOKEN` secret to private repo settings
- [ ] Update `.gitignore` in public repo (keep only `.pyc` and `__init__.py`)
- [ ] Update bootstrap cell in notebooks to use sparse-checkout
- [ ] Test: Make change in private repo → Verify it appears compiled in public repo
- [ ] Update README with IP protection notice

---

## Next Steps in Aider

When you resume work in Claude + Aider:

```
"I want to set up a two-repository approach for IP protection:
1. Create build.py that compiles .py files to .pyc in __pycache__
2. Create GitHub Actions workflow that pushes compiled files to public repo
3. Update notebook bootstrap cell to use sparse-checkout for compiled files only
4. Create/update .gitignore to keep only .pyc files, remove .py sources from public repo"
```

Or more specifically:

```
"Help me create the GitHub Actions workflow that:
1. Builds compiled .pyc files from my private repo
2. Pushes ONLY the compiled files to my public distribution repo
3. Keeps source code private"
```

---

## Questions for Claude in Aider

- *"Create the `build.py` script that compiles Python files to `.pyc` in `__pycache__` directories"*
- *"Create the GitHub Actions workflow that builds and publishes compiled bytecode to the public repo"*
- *"Update the Colab bootstrap cell to use sparse-checkout for compiled files"*
- *"Set up the `.gitignore` so public repo only contains `.pyc` and `__init__.py`, no source `.py` files"*
- *"How do I manage the GitHub Personal Access Token for the workflow?"*

---

**Status:** Ready for implementation  
**Recommended:** Start with creating the private repo, then build.py, then GitHub Actions workflow  
**Timeline:** 2-3 development sessions to fully implement


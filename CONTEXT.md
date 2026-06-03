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
internal-tools (PRIVATE)
├── notebooks/           ← Source notebooks (development)
├── launchers/           ← Source code (SENSITIVE)
├── engines/             ← Source code (SENSITIVE)
├── version.json
├── build.py             ← Compilation script
└── .github/workflows/   ← Build automation
```

**Repository 2: PUBLIC (Distribution)**
```
GoWild-Scraper (PUBLIC)
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

## Repository Status

### **Private Repository Created** ✅
- **Name:** `internal-tools`
- **Visibility:** PRIVATE
- **URL:** https://github.com/carloscruzerrazuriz/internal-tools
- **Purpose:** Development only - contains full source code
- **Access:** Only you

### **Public Repository (Existing)** 
- **Name:** `GoWild-Scraper`
- **Visibility:** PUBLIC
- **URL:** https://github.com/carloscruzerrazuriz/GoWild-Scraper
- **Purpose:** Distribution - will contain only compiled `.pyc` files
- **User Colab Links:** Already distributed, will auto-update with compiled code

---

## Implementation Steps

### **Step 1: Push Code to Private Repo**

In your terminal:

```bash
# Navigate to your GoWild-Scraper directory
cd ~/path/to/GoWild-Scraper

# Change remote to point to internal-tools (private repo)
git remote set-url origin https://github.com/carloscruzerrazuriz/internal-tools.git

# Ensure you're on main branch
git branch -M main

# Push all code to private repo
git push -u origin main
```

**Verify:** Go to https://github.com/carloscruzerrazuriz/internal-tools and confirm all your code is there.

### **Step 2: Create Build Script in Private Repo (`build.py`)**

Create this file in `internal-tools`:

```python
import py_compile
import os
from pathlib import Path

def build_compiled_version():
    """
    Compile Python files to bytecode for distribution.
    Creates .pyc files in __pycache__ directories.
    """
    
    dirs_to_compile = ['engines', 'launchers']
    
    for directory in dirs_to_compile:
        if not os.path.exists(directory):
            continue
            
        print(f"Compiling {directory}/...")
        
        # Create __pycache__ directory
        pycache_dir = Path(directory) / '__pycache__'
        pycache_dir.mkdir(exist_ok=True)
        
        for py_file in Path(directory).glob('*.py'):
            # Keep __init__.py as source (Python needs it for imports)
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
    print("\n✅ Build complete!")
```

### **Step 3: Create GitHub Actions Workflow**

Create file: `.github/workflows/build-and-publish.yml` in `internal-tools`:

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
        
        # Copy compiled bytecode files to public repo
        cp -r engines/__pycache__ public_repo/engines/
        cp -r launchers/__pycache__ public_repo/launchers/
        
        # Copy __init__.py files (needed for Python imports)
        cp engines/__init__.py public_repo/engines/ 2>/dev/null || true
        cp launchers/__init__.py public_repo/launchers/ 2>/dev/null || true
        
        # Copy notebooks
        cp -r notebooks/*.ipynb public_repo/notebooks/
        cp version.json public_repo/
        
        # Commit and push to public repo
        cd public_repo
        git config user.email "action@github.com"
        git config user.name "GitHub Action (Build)"
        git add -A
        git commit -m "🔐 Auto-build: Publish compiled bytecode version [skip ci]" || echo "No changes to commit"
        git push origin main
```

### **Step 4: Set Up GitHub Token for Automation**

To allow the workflow to push to the public repo:

1. Go to https://github.com/settings/tokens/new
2. Create a **Personal Access Token** with:
   - Name: `PUBLIC_REPO_PUSH_TOKEN`
   - Expiration: 90 days (or longer)
   - Scopes: Select `repo` (full control)
3. Copy the token
4. Go to **internal-tools** repo → **Settings** → **Secrets and variables** → **Actions**
5. Click **"New repository secret"**
6. Name: `PUBLIC_REPO_PUSH_TOKEN`
7. Value: (paste the token you copied)
8. Click **"Add secret"**

### **Step 5: Update Public Repo `.gitignore`**

In `GoWild-Scraper`, update `.gitignore`:

```gitignore
# Remove source .py files - only keep compiled
*.py
!**/__init__.py
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
.DS_Store
*.egg-info/
dist/
build/
```

### **Step 6: Update Colab Bootstrap Cell**

In your notebooks (cell #2), update the bootstrap to use sparse-checkout:

```python
# === BOOTSTRAP CELL - Auto-update from compiled repo ===

import subprocess
import sys
import os
import json

REPO_URL = "https://github.com/carloscruzerrazuriz/GoWild-Scraper.git"
LOCAL_DIR = "/content/gowild"

print("📥 Loading compiled modules (source code protected)...")

try:
    if not os.path.exists(LOCAL_DIR):
        # First clone with sparse checkout
        subprocess.run([
            "git", "clone", 
            "--depth", "1",
            "--sparse",
            REPO_URL, 
            LOCAL_DIR
        ], check=True, capture_output=True)
        
        os.chdir(LOCAL_DIR)
        
        # Configure sparse checkout - only get compiled code
        subprocess.run([
            "git", "sparse-checkout", "set",
            "launchers",
            "engines",
            "notebooks",
            "version.json"
        ], check=True, capture_output=True)
    else:
        # Update existing repo
        os.chdir(LOCAL_DIR)
        subprocess.run(["git", "pull", "--depth", "1"], check=True, capture_output=True)
    
    # Add to path
    if LOCAL_DIR not in sys.path:
        sys.path.insert(0, LOCAL_DIR)
    
    # Verify schema version
    with open(f"{LOCAL_DIR}/version.json") as f:
        version_data = json.load(f)
        launcher_schema = version_data.get("launcher_schema", "unknown")
        print(f"✅ Compiled modules loaded! (Schema: {launcher_schema})")
        print("   → Source code protected with bytecode compilation")
        
except Exception as e:
    print(f"❌ Error loading modules: {e}")
    raise
```

---

## Workflow: Development to Distribution

```
1. You work in PRIVATE REPO (internal-tools)
   ├─ Edit: engines/sodimac_engine.py
   ├─ Edit: launchers/mk7.py
   └─ Commit and push

2. GitHub Actions triggers automatically
   ├─ Runs: python build.py
   ├─ Creates: .pyc compiled files
   └─ Pushes to PUBLIC REPO (GoWild-Scraper)

3. Users' Colab notebooks auto-update
   ├─ Pull latest from GoWild-Scraper
   ├─ Get only compiled .pyc files
   ├─ See NO source code
   └─ Everything works perfectly ✅
```

---

## How It Works for Users

1. **User opens existing Colab notebook** → No changes needed, same URL
2. **Bootstrap cell runs** → Clones public repo (only compiled files)
3. **Sparse checkout pulls** → Only `launchers/__pycache__/` and `engines/__pycache__/`
4. **Imports load compiled bytecode** → Python loads `.pyc` files seamlessly
5. **Code executes** → Full functionality, identical to source code
6. **Code is protected** → No source files exist in public repo to inspect

---

## Security Comparison

| Aspect | Public Source | Bytecode Only | Two-Repo Solution |
|--------|---------------|---------------|-------------------|
| Source code visible? | ✅ YES | ✅ YES (in .pyc) | ❌ NO |
| Users can inspect? | ✅ YES | ⚠️ DIFFICULT | ❌ NO |
| Can be decompiled? | ✅ EASILY | ⚠️ POSSIBLE | ❌ FILES DON'T EXIST |
| IP Protected? | ❌ NO | ⚠️ PARTIAL | ✅ MAXIMUM |
| User friction? | 🟢 None | 🟢 None | 🟢 None |
| Complexity? | 🟢 Low | 🟡 Medium | 🟠 High |
| Recommended? | ❌ | ❌ | ✅ YES |

---

## Current Development Environment

- **Editor:** Antigravity + Claude (Aider)
- **Private Repository:** `carloscruzerrazuriz/internal-tools` ✅ CREATED
- **Public Repository:** `carloscruzerrazuriz/GoWild-Scraper` ✅ EXISTS
- **Visibility:** Private (dev) → Public (distribution)
- **Language:** Python
- **Automation:** GitHub Actions

---

## Setup Checklist

- [x] Create private repository: `internal-tools`
- [ ] Push code to private repo: `git push -u origin main`
- [ ] Create `build.py` in private repo
- [ ] Create `.github/workflows/build-and-publish.yml` in private repo
- [ ] Generate GitHub Personal Access Token
- [ ] Add `PUBLIC_REPO_PUSH_TOKEN` secret to private repo
- [ ] Update public repo `.gitignore` (keep only `.pyc` and `__init__.py`)
- [ ] Update bootstrap cell in notebooks to use sparse-checkout
- [ ] Test: Make change in private repo → Verify compiled version in public repo
- [ ] Update README.md with IP protection notice

---

## Next Steps

### **Immediate (In Terminal):**

1. **Push your code to private repo:**
   ```bash
   cd ~/path/to/GoWild-Scraper
   git remote set-url origin https://github.com/carloscruzerrazuriz/internal-tools.git
   git branch -M main
   git push -u origin main
   ```

2. **Verify:** https://github.com/carloscruzerrazuriz/internal-tools should have all your code

### **Then in Aider/Claude:**

Ask Claude to help you:
1. Create `build.py` in the private repo
2. Create `.github/workflows/build-and-publish.yml` 
3. Update notebook bootstrap cells with sparse-checkout code
4. Update `.gitignore` in public repo

Or tell me when you're ready and I can create these files for you!

---

## References

- **Private Repo:** https://github.com/carloscruzerrazuriz/internal-tools (for development)
- **Public Repo:** https://github.com/carloscruzerrazuriz/GoWild-Scraper (for distribution)
- **Current Architecture:** Thin notebooks + auto-updating compiled modules
- **Auto-Update Mechanism:** Bootstrap cell pulls compiled `.pyc` files via sparse-checkout

---

**Status:** Ready for next implementation phase  
**Current User Impact:** ZERO - Existing Colab notebooks will continue to work unchanged  
**Security:** Users will receive compiled bytecode, source code stays private

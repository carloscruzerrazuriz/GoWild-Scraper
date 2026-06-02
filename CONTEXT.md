# GoWild-Scraper: IP Protection Context

**Date:** 2026-06-02  
**Goal:** Protect intellectual property by preventing users from reading/stealing the source code while maintaining full functionality in Colab notebooks.

---

## Problem Statement

- **Current State:** Repository is `public` with source code visible
- **Concern:** Users can view and steal the scraping engine logic (sodimac, falabella, construmart, maestra, ferni)
- **Objective:** Distribute Colab notebooks that work perfectly, but with encrypted/compiled code that prevents IP theft
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

### **Option 1: Compiled Python (.pyc files)** ⭐ RECOMMENDED
- **How:** Convert `.py` to compiled bytecode (`.pyc`)
- **Protection Level:** HIGH - Hard to reverse-engineer
- **Implementation:** Python's built-in `py_compile` module
- **Trade-offs:** 
  - Bytecode is harder to decompile than source
  - You need separate dev branch for source files
  - Still technically decompilable with effort, but deters casual theft
- **For Your Project:** BEST option because:
  - Simple to implement with GitHub Actions
  - Minimal changes to existing architecture
  - Auto-update mechanism still works
  - Users' Colab notebooks import compiled modules seamlessly

### **Option 2: Obfuscation (PyArmor/Cython)**
- **How:** Scramble variable names, strings, logic flow
- **Protection Level:** MEDIUM - Harder to read, but decompilable
- **Trade-offs:** Extra build step, slightly slower imports
- **Recommendation:** Combine with Option 1 for extra protection

### **Option 3: Encryption at Runtime**
- **How:** Encrypt code, decrypt in Colab before execution
- **Protection Level:** LOW-MEDIUM - Key must be in code somewhere
- **Trade-offs:** Not recommended; keys can be extracted

### **Option 4: Private Repository**
- **How:** Make repo private, distribute via GitHub authentication
- **Protection Level:** MEDIUM - Code still visible to authenticated users
- **Trade-offs:** Users need GitHub tokens, breaks seamless Colab distribution
- **Not Recommended:** Complicates user experience

### **Option 5: Wheel Distribution (.whl)**
- **How:** Package compiled code as distributable wheel
- **Protection Level:** HIGH - Full binary protection
- **Trade-offs:** Complex distribution, harder to maintain auto-updates
- **Not Recommended:** Overkill for this use case

---

## Recommended Implementation: Compiled Bytecode + GitHub Actions

### **Why This Approach?**

1. ✅ **Maximum compatibility** - Existing Colab notebooks work unchanged
2. ✅ **Auto-updates preserved** - Users pull latest compiled code on each run
3. ✅ **Easy maintenance** - GitHub Actions automates compilation
4. ✅ **IP Protected** - `.pyc` files resist casual reverse-engineering
5. ✅ **No user friction** - No authentication or access codes needed
6. ✅ **Professional** - Industry-standard approach for protecting proprietary code

### **Implementation Steps**

#### **Step 1: Create Build Script (`build.py`)**

```python
import py_compile
import os
import shutil
from pathlib import Path

def build_compiled_version():
    """Compile Python files to bytecode"""
    
    # Directories to compile
    dirs_to_compile = ['engines', 'launchers']
    
    for directory in dirs_to_compile:
        if not os.path.exists(directory):
            continue
            
        print(f"Compiling {directory}/...")
        
        for py_file in Path(directory).glob('*.py'):
            # Skip __init__.py to preserve imports
            if py_file.name == '__init__.py':
                continue
            
            try:
                py_compile.compile(str(py_file), doraise=True)
                print(f"  ✓ {py_file.name} compiled")
                
            except py_compile.PyCompileError as e:
                print(f"  ✗ {py_file.name}: {e}")

if __name__ == "__main__":
    build_compiled_version()
    print("\n✅ Build complete! Compiled files ready.")
```

#### **Step 2: Create GitHub Actions Workflow (`.github/workflows/build.yml`)**

```yaml
name: Build Compiled Version

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
    
    - name: List compiled files
      run: find engines launchers -name "*.pyc" -type f
    
    - name: Commit and push compiled bytecode
      run: |
        git config --local user.email "action@github.com"
        git config --local user.name "GitHub Action (Build)"
        git add -A
        git commit -m "🔐 Auto-build: Compiled bytecode version [skip ci]" || echo "No changes to commit"
        git push
```

#### **Step 3: Update `.gitignore`**

```
# Keep source for development, but compile before push
__pycache__/
*.py[cod]
*$py.class
*.so

# Compiled bytecode is safe to commit
!*.pyc
```

#### **Step 4: Workflow in Aider/Claude**

When developing with Claude in Aider:

```
Steps to maintain:
1. Edit engines/*.py and launchers/*.py normally in your local environment
2. Run: python build.py (creates .pyc files)
3. Git push (GitHub Actions verifies compilation)
4. Only .pyc compiled files are in the public repo
5. Source .py files stay in your local `.gitignore` or dev branch
```

---

## How It Works for Users

1. **User clicks Colab link** → Opens latest notebook from repo
2. **Notebook runs bootstrap cell** → `git clone --depth 1` pulls repo (includes compiled `.pyc` files)
3. **Boot imports modules** → Python loads `.pyc` compiled versions seamlessly
4. **Code executes normally** → User gets full functionality
5. **Code is unreadable** → `.pyc` files are bytecode, not human-readable source

---

## Security Notes

### **What's Protected:**
- ✅ Scraping logic (sodimac, falabella, construmart engines)
- ✅ Proprietary selectors and patterns
- ✅ Algorithm implementations
- ✅ Business logic in launchers

### **What's NOT Protected:**
- ⚠️ `.pyc` files CAN be decompiled with tools like `uncompyle6`, but:
  - Requires additional effort
  - Results are low-quality, variable names are gone
  - Deters 95% of casual theft
  - Industry-standard protection (used by major companies)

### **If Maximum Security Needed:**
Combine with PyArmor obfuscation:
```bash
pyarmor obfuscate --restrict engines/sodimac_engine.py
```

---

## Current Development Environment

- **Editor:** Antigravity + Claude (Aider)
- **Repository:** `carloscruzerrazuriz/GoWild-Scraper`
- **Visibility:** Public (intentional - for Colab distribution)
- **Language:** Python
- **Main Branches:** `main` (production)

---

## Next Steps in Aider

When you resume work in Claude + Aider:

1. **Create `build.py`** with compilation logic
2. **Create `.github/workflows/build.yml`** for automated compilation
3. **Set up development workflow:**
   - Edit source files locally
   - Run `python build.py` to create `.pyc` files
   - Commit and push
   - GitHub Actions verifies compilation
4. **Test:** Verify Colab notebooks still work with compiled `.pyc` modules
5. **Document:** Update README with "This repo uses compiled bytecode for IP protection"

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `build.py` | Create | Compilation script |
| `.github/workflows/build.yml` | Create | Automated build workflow |
| `.gitignore` | Modify | Ensure `.pyc` files are tracked |
| `README.md` | Modify | Add note about compiled distribution |
| `CONTEXT.md` | Create (this file) | Reference for future development |

---

## Questions to Ask Claude in Aider

```
"Create a build.py script that compiles all .py files in engines/ 
and launchers/ to bytecode for IP protection, then set up a 
GitHub Actions workflow to run this automatically on push."

"Update .gitignore to track .pyc compiled files while keeping 
source files in development."

"After compilation, verify that Colab notebooks can still import 
and run the compiled modules."
```

---

## References

- **Repository:** https://github.com/carloscruzerrazuriz/GoWild-Scraper
- **Current Architecture:** Thin notebooks + auto-updating engines from repo
- **Auto-Update Mechanism:** Bootstrap cell does `git clone --depth 1` + path injection
- **Target Protection:** Make engines/ and launchers/ source code unreadable to users

---

**Status:** Ready for implementation in Aider environment  
**Recommendation:** Start with `build.py` creation, then GitHub Actions workflow

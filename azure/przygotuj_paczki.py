"""Kopiuje pakiet `parking` do paczek Azure (Function App i App Service).

Uruchom z katalogu głównego projektu:  python azure/przygotuj_paczki.py
Potem:
  cd azure/functionapp && func azure functionapp publish <NAZWA_FUNCTION_APP>
  cd azure/webapp && az webapp up --name <NAZWA_WEBAPP> --runtime PYTHON:3.11
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "parking"

for target in (ROOT / "azure" / "functionapp" / "parking", ROOT / "azure" / "webapp" / "parking"):
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SRC, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"Skopiowano {SRC.relative_to(ROOT)} -> {target.relative_to(ROOT)}")

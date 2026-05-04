from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs"

FILES = [
    BASE / "data" / "normas_manifest.json",
    BASE / "data" / "instrucoes_tecnicas_manifest.json",
    BASE / "data" / "normas_com_texto.json",
    BASE / "data" / "links_nao_pdf.json",
    BASE / "data" / "erros_download.json",
    BASE / "normas_manifest.json",
    BASE / "instrucoes_tecnicas_manifest.json",
    BASE / "normas_com_texto.json",
    BASE / "templates" / "formularios" / "modelos_laudos.json",
]

ok = True
for path in FILES:
    if not path.exists():
        print(f"AUSENTE  {path.relative_to(ROOT)}")
        ok = False
        continue
    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except Exception as exc:
        print(f"INVÁLIDO {path.relative_to(ROOT)} :: {type(exc).__name__}: {exc}")
        ok = False
        continue

    # Regrava em JSON válido e legível, sem BOM e sem controle bruto.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    size = path.stat().st_size
    print(f"OK       {path.relative_to(ROOT)} :: {size:,} bytes")

if not ok:
    print("\nAlgum arquivo está ausente ou inválido. Rode novamente scripts/sincronizar_normas_cbmmg.py e depois este validador.")
    sys.exit(1)

print("\nTodos os JSONs esperados são válidos e foram regravados em UTF-8/JSON legível.")

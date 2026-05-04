#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida JSONs publicados no GitHub Pages da base CBMMG."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = [
    ROOT / "docs" / "templates" / "formularios" / "modelos_laudos.json",
    ROOT / "docs" / "data" / "normas_manifest.json",
    ROOT / "docs" / "data" / "instrucoes_tecnicas_manifest.json",
    ROOT / "docs" / "data" / "normas_com_texto.json",
    ROOT / "docs" / "data" / "links_nao_pdf.json",
    ROOT / "docs" / "data" / "erros_download.json",
    ROOT / "docs" / "normas_com_texto.json",
    ROOT / "docs" / "normas_manifest.json",
    ROOT / "docs" / "instrucoes_tecnicas_manifest.json",
]

falhas: list[str] = []
for path in PATHS:
    if not path.exists():
        print(f"AUSENTE  {path.relative_to(ROOT)}")
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
        size = path.stat().st_size
        print(f"OK       {path.relative_to(ROOT)} ({size} bytes)")
    except Exception as exc:  # noqa: BLE001
        falhas.append(f"{path.relative_to(ROOT)}: {exc}")
        print(f"INVÁLIDO {path.relative_to(ROOT)}: {exc}")

if falhas:
    raise SystemExit("\n".join(falhas))

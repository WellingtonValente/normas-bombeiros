#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repara JSONs com quebras de linha cruas dentro de strings.

Uso: python scripts/reparar_jsons_invalidos.py

Motivo: algumas versões antigas do hotfix escreveram JSON aparentemente
"achatado" ou com LF literal dentro de campos textuais. Isso é inválido para
parsers estritos, inclusive o GPT Actions. Este script corrige LF/CR/TAB crus
apenas quando estão dentro de strings JSON e regrava os arquivos com json.dump.
"""
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


def escape_controles_em_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                # CR isolado ou CRLF dentro de string vira \n.
                out.append("\\n")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            if ord(ch) < 32:
                out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_string = True
    return "".join(out)


def carregar_json(path: Path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        fixed = escape_controles_em_strings(raw)
        return json.loads(fixed), True


def main() -> int:
    falhas: list[str] = []
    for path in PATHS:
        rel = path.relative_to(ROOT)
        if not path.exists():
            print(f"AUSENTE  {rel}")
            continue
        try:
            obj, repaired = carregar_json(path)
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            status = "REPARADO" if repaired else "OK"
            print(f"{status:<8} {rel} ({path.stat().st_size} bytes)")
        except Exception as exc:  # noqa: BLE001
            falhas.append(f"{rel}: {exc}")
            print(f"FALHA    {rel}: {exc}")
    if falhas:
        raise SystemExit("\n".join(falhas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

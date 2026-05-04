#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compara dois manifestos de ITs gerados pelo sincronizador.

Uso:
  python scripts/comparar_manifestos.py antigo.json novo.json --out relatorio_diff.json
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any


def load_docs(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = data.get("instrucoes_tecnicas") or data.get("normas") or data.get("documentos") or []
    out = {}
    for d in docs:
        key = d.get("numero_it") or d.get("titulo") or d.get("url")
        if key:
            out[str(key)] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("antigo")
    ap.add_argument("novo")
    ap.add_argument("--out", default="relatorio_diff.json")
    args = ap.parse_args()

    antigo = load_docs(Path(args.antigo))
    novo = load_docs(Path(args.novo))

    antigas = set(antigo)
    novas = set(novo)

    rel = {
        "novas": [novo[k] for k in sorted(novas - antigas)],
        "removidas": [antigo[k] for k in sorted(antigas - novas)],
        "alteradas_sha256": [],
        "inalteradas": [],
    }
    for k in sorted(antigas & novas):
        a = antigo[k]
        n = novo[k]
        if a.get("sha256") and n.get("sha256") and a.get("sha256") != n.get("sha256"):
            rel["alteradas_sha256"].append({"chave": k, "antigo": a, "novo": n})
        else:
            rel["inalteradas"].append(n)

    Path(args.out).write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "novas": len(rel["novas"]),
        "removidas": len(rel["removidas"]),
        "alteradas_sha256": len(rel["alteradas_sha256"]),
        "inalteradas": len(rel["inalteradas"]),
        "saida": args.out,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

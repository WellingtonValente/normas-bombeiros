#!/usr/bin/env python3
"""Build a bounded, read-only API for GPT Actions from the retained collection.

No network calls, no claim of legal currency and no conversation storage.
Every generated JSON response is validated against MAX_RESPONSE_BYTES.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_RESPONSE_BYTES = 24000
TEXT_CHARS = 6000
PAGE_ITEMS = 8
NOTICE = "Acervo auxiliar. Data de coleta não comprova vigência. Confirme ato, emendas e transição na fonte oficial."


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fold(value):
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", fold(value)).strip("-")[:60] or "outros"


def state(doc):
    """Do not propagate the legacy 'vigente/listada' heuristic."""
    evidence = fold(doc.get("titulo", "") + " " + unquote(doc.get("url", "")))
    if "legislacaoantiga" in evidence or "substituid" in evidence:
        return "historico", "Título ou caminho oficial indica conteúdo histórico."
    if "revogad" in evidence:
        return "revogacao_indicada", "Indicação de revogação no título/caminho; conferir alcance no ato."
    if "minuta" in evidence or "consulta-publica" in evidence or "consulta publica" in evidence:
        return "proposta", "Consulta pública/minuta não equivale a obrigação vigente."
    return "nao_verificada", "Listagem e disponibilidade não comprovam vigência."


def it_number(doc):
    # Some legacy entries inherited a number from a broad HTML parent.
    own = doc.get("titulo", "") + " " + unquote(urlparse(doc.get("url", "")).path)
    match = re.search(r"\bIT[ _.-]*0*([0-9]{1,2})(?!\d)", own, re.I)
    return f"{int(match.group(1)):02d}" if match else None


def text_parts(text):
    """Lossless slices; PDF page references remain distinct from IT item numbers."""
    markers = [(m.start(), int(m.group(1))) for m in re.finditer(r"--- PÁGINA (\d+) ---", text)]
    for start in range(0, len(text), TEXT_CHARS):
        end = min(start + TEXT_CHARS, len(text))
        first = next((n for pos, n in reversed(markers) if pos <= start), None)
        within = [n for pos, n in markers if start <= pos < end]
        pages = sorted(set(([first] if first else []) + within))
        yield text[start:end], pages


def load_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build(out: Path):
    manifest = load_json(out / "data/normas_manifest.json")
    corpus = load_json(out / "data/normas_com_texto.json")
    if not manifest or not corpus or not manifest.get("documentos") or not corpus.get("normas"):
        raise ValueError("Base ausente/vazia. API anterior deve ser preservada.")
    metadata = manifest.get("metadata", {})
    collected = metadata.get("data_coleta")
    corpus_hash = hashlib.sha256(packed([manifest, corpus])).hexdigest()
    api = out / "api/v1"
    responses = {}

    def emit(path, value):
        payload = packed(value)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError(f"Resposta excede {MAX_RESPONSE_BYTES} bytes: {path} ({len(payload)})")
        responses[path] = payload

    def paginate(prefix, items, extra=None):
        count = max(1, (len(items) + PAGE_ITEMS - 1) // PAGE_ITEMS)
        for page in range(1, count + 1):
            emit(f"{prefix}/{page}.json", {"pagina": page, "total_paginas": count,
                 "total_registros": len(items), "proxima_pagina": page + 1 if page < count else None,
                 "data_coleta": collected, "aviso": NOTICE, **(extra or {}),
                 "items": items[(page-1)*PAGE_ITEMS:page*PAGE_ITEMS]})
        return count

    text_by_url = {d["url"]: d for d in corpus["normas"]}
    docs = {d["url"]: d for d in manifest["documentos"]}
    docs.update({k: {**docs.get(k, {}), **v} for k, v in text_by_url.items()})
    its, categories = defaultdict(list), defaultdict(list)
    all_summaries = []
    for url, d in sorted(docs.items()):
        host = (urlparse(url).hostname or "").lower()
        if host != "bombeiros.mg.gov.br" and not host.endswith(".bombeiros.mg.gov.br"):
            continue
        ident = hashlib.sha256((url + "\n" + str(d.get("sha256", ""))).encode()).hexdigest()[:24]
        status, evidence = state(d)
        number = it_number(d)
        text = d.get("texto", "")
        if not text and d.get("texto_path"):
            candidate = (out / d["texto_path"]).resolve()
            if candidate.is_relative_to(out.resolve()) and candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
        if text.startswith("[ERRO DE EXTRAÇÃO:"):
            text = ""
        summary = {"id": ident, "titulo": d.get("titulo", "")[:350], "numero_it": number,
                   "categoria": d.get("categoria", "Outros"), "edicao": d.get("edicao"),
                   "alteracao": d.get("alteracao"), "situacao": status, "evidencia_situacao": evidence,
                   "url_oficial": url, "sha256_pdf": d.get("sha256"), "data_coleta": d.get("data_coleta") or collected,
                   "coleta_estado": d.get("coleta_estado", "acervo_herdado"),
                   "paginas_pdf": d.get("paginas"), "tem_texto": bool(text)}
        chunks = []
        parts = list(text_parts(text))
        for n, (part, pages) in enumerate(parts, 1):
            path = f"documentos/{ident}/trechos/{n}.json"
            emit(path, {"documento": summary, "trecho": n, "total_trechos": len(parts),
                        "paginas_pdf": pages, "texto": part, "aviso": NOTICE})
            chunks.append({"trecho": n, "paginas_pdf": pages,
                           "inicio": re.sub(r"\s+", " ", part[:140]), "caminho": "/api/v1/" + path})
        index_pages = paginate(f"documentos/{ident}/indice", chunks, {"documento": summary})
        summary = {**summary, "total_trechos": len(parts), "paginas_indice": index_pages,
                   "indice": f"/api/v1/documentos/{ident}/indice/1.json"}
        all_summaries.append(summary)
        if number:
            its[number].append(summary)
        categories[slug(summary["categoria"])].append(summary)

    if not all_summaries:
        raise ValueError("Nenhum documento válido; API anterior preservada.")
    by_it = [{"numero_it": num, "documentos": len(items),
              "paginas": paginate(f"its/{num}", items), "caminho": f"/api/v1/its/{num}/1.json"}
             for num, items in sorted(its.items())]
    by_category = [{"categoria": name, "documentos": len(items),
                    "paginas": paginate(f"catalogo/{name}", items), "caminho": f"/api/v1/catalogo/{name}/1.json"}
                   for name, items in sorted(categories.items())]
    emit("catalogo.json", {"versao_api": "3.0.0", "sha256_base": corpus_hash,
         "data_coleta": collected, "total_documentos": len(all_summaries), "aviso": NOTICE,
         "instrucoes_tecnicas": by_it, "categorias": by_category})
    sync = load_json(out / "data/sync_status.json", {})
    emit("status.json", {"versao_api": "3.0.0", "sha256_base": corpus_hash, "data_coleta": collected,
         "atualidade_normativa": "nao_garantida", "ultima_tentativa": sync.get("ultima_tentativa"),
         "resultado_coleta": sync.get("status", "sem_verificacao_recente"),
         "promocao_parcial": sync.get("promocao_parcial", False),
         "coleta_ok": sync.get("ok"), "erros_coleta_base": metadata.get("total_erros"),
         "limite_resposta_bytes": MAX_RESPONSE_BYTES, "total_documentos": len(all_summaries),
         "aviso": NOTICE, "memoria": "Versiona base técnica e configuração. Não armazena conversas nem dados de clientes."})
    config = load_json(Path(__file__).resolve().parents[1] / "config/fontes.json", {"fontes": []})
    emit("fontes.json", config)
    # Validate everything before writing any endpoint. Existing immutable IDs are retained.
    for path, payload in responses.items():
        target = api / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
    print(json.dumps({"documentos": len(all_summaries), "respostas": len(responses),
                      "maior_resposta_bytes": max(map(len, responses.values())),
                      "data_coleta": collected, "sha256_base": corpus_hash}, ensure_ascii=False))
    return responses


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs"))
    build(parser.parse_args().out)

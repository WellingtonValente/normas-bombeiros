#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincronizador oficial da base CBMMG para GitHub Pages.

Objetivo:
1. Ler a página oficial de Legislação e Normas Técnicas do CBMMG.
2. Identificar links para documentos, priorizando PDFs do domínio bombeiros.mg.gov.br.
3. Baixar PDFs oficiais, calcular SHA-256 e criar manifesto auditável.
4. Extrair texto pesquisável dos PDFs quando --extract-text for usado.
5. Publicar JSON/JSONL estático para Actions do Custom GPT.

Observação: este script não baixa nem replica texto integral de normas ABNT/NBR.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OFICIAL_URL = "https://www.bombeiros.mg.gov.br/normastecnicas"
USER_AGENT = "RWValente-CBMMG-Sync/2.1 (+GitHub Pages; educational mirror)"
TIMEOUT = 45
MAX_RETRIES = 3
CHUNK_SIZE_CHARS = 4500
CHUNK_OVERLAP_CHARS = 350


@dataclasses.dataclass
class Documento:
    titulo: str
    url: str
    categoria: str
    subcategoria: str | None = None
    numero_it: str | None = None
    edicao: str | None = None
    situacao: str | None = None
    alteracao: str | None = None
    arquivo: str | None = None
    sha256: str | None = None
    tamanho_bytes: int | None = None
    paginas: int | None = None
    texto_path: str | None = None
    origem: str = "CBMMG - página oficial de normas técnicas"

    def asdict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def slugify(value: str, max_len: int = 120) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (value[:max_len].strip("-") or "documento")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def salvar_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/pdf,*/*",
    })
    return session


def fetch(session: requests.Session, url: str) -> requests.Response:
    last_exc: Exception | None = None
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if tentativa < MAX_RETRIES:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {last_exc}")


def is_probably_pdf(response: requests.Response, url: str) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return (
        "application/pdf" in content_type
        or urlparse(url).path.lower().endswith(".pdf")
        or response.content[:5] == b"%PDF-"
    )


def parse_it_metadata(titulo: str, complemento: str = "") -> tuple[str | None, str | None, str | None, str | None]:
    full = f"{titulo} {complemento}".strip()
    numero_it = None
    edicao = None
    alteracao = None

    m = re.search(r"\bIT\s*0*([0-9]{1,2})\b", full, flags=re.I)
    if m:
        numero_it = f"{int(m.group(1)):02d}"

    m = re.search(r"(\d+)\s*[ªaºo]?\s*edi[cç][aã]o", full, flags=re.I)
    if m:
        edicao = f"{m.group(1)}ª Edição"

    situacao = "revogada" if "revogad" in full.lower() else "vigente/listada"

    m = re.search(r"(Portaria\s*n?[ºo]?\s*\d+/?\d*|Emenda\s*n?[ºo]?\s*\d+/?\d*)", full, flags=re.I)
    if m:
        alteracao = m.group(1).strip()

    return numero_it, edicao, situacao, alteracao


def section_name(text: str) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean or "Sem seção"


def extrair_links_da_pagina(html: str, base_url: str) -> list[Documento]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.find(id=re.compile("conteudo|content", re.I)) or soup.body or soup

    categoria_atual = "Sem seção"
    subcategoria_atual: str | None = None
    documentos: list[Documento] = []

    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a"], recursive=True):
        tag = el.name.lower()
        texto = re.sub(r"\s+", " ", el.get_text(" ", strip=True))

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            nome = section_name(texto)
            if re.fullmatch(r"20\d{2}|19\d{2}|\d{4}", nome):
                subcategoria_atual = nome
            elif nome:
                categoria_atual = nome
                subcategoria_atual = None
            continue

        href_raw = el.get("href")
        if not href_raw:
            continue

        href = urljoin(base_url, href_raw)
        titulo = texto or href
        if titulo.lower().startswith(("ir para", "início", "facebook", "instagram", "youtube", "linkedin")):
            continue

        parent_li = el.find_parent("li")
        complemento = re.sub(r"\s+", " ", parent_li.get_text(" ", strip=True)) if parent_li else titulo
        numero_it, edicao, situacao, alteracao = parse_it_metadata(titulo, complemento)

        documentos.append(
            Documento(
                titulo=titulo,
                url=href,
                categoria=categoria_atual,
                subcategoria=subcategoria_atual,
                numero_it=numero_it,
                edicao=edicao,
                situacao=situacao,
                alteracao=alteracao,
            )
        )

    vistos: set[str] = set()
    unicos: list[Documento] = []
    for doc in documentos:
        if doc.url in vistos:
            continue
        vistos.add(doc.url)
        unicos.append(doc)
    return unicos


def extract_pdf_text(pdf_path: Path) -> tuple[str, int | None]:
    try:
        import fitz  # type: ignore

        textos: list[str] = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                t = page.get_text("text") or ""
                if t.strip():
                    textos.append(f"\n\n--- PÁGINA {i} ---\n{t.strip()}")
            return "".join(textos).strip(), len(doc)
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(pdf_path))
            textos = []
            for i, page in enumerate(reader.pages, start=1):
                t = page.extract_text() or ""
                if t.strip():
                    textos.append(f"\n\n--- PÁGINA {i} ---\n{t.strip()}")
            return "".join(textos).strip(), len(reader.pages)
        except Exception as exc:  # noqa: BLE001
            return f"[ERRO DE EXTRAÇÃO: {exc}]", None


def chunk_text(text: str, size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> Iterable[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        if end < n:
            break_at = text.rfind("\n\n", start, end)
            if break_at > start + int(size * 0.6):
                end = break_at
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def download_e_processar(
    session: requests.Session,
    documentos: list[Documento],
    out: Path,
    extract_text: bool,
    only_cbmmg_host: bool,
) -> tuple[list[Documento], list[dict[str, Any]], list[dict[str, Any]]]:
    pdf_dir = out / "pdf"
    text_dir = out / "texto"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    docs_pdf: list[Documento] = []
    nao_pdf: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []

    for idx, doc in enumerate(documentos, start=1):
        host = urlparse(doc.url).netloc.lower()
        if only_cbmmg_host and "bombeiros.mg.gov.br" not in host:
            nao_pdf.append({**doc.asdict(), "motivo": "host externo ignorado"})
            continue

        try:
            response = fetch(session, doc.url)
            if not is_probably_pdf(response, doc.url):
                nao_pdf.append({
                    **doc.asdict(),
                    "motivo": "não retornou PDF",
                    "content_type": response.headers.get("content-type"),
                })
                continue

            digest = sha256_bytes(response.content)
            prefix = f"it-{doc.numero_it}" if doc.numero_it else slugify(doc.categoria)
            fname = f"{prefix}-{slugify(doc.titulo)}-{digest[:12]}.pdf"
            pdf_path = pdf_dir / fname
            if not pdf_path.exists() or pdf_path.read_bytes() != response.content:
                pdf_path.write_bytes(response.content)

            doc.arquivo = f"pdf/{fname}"
            doc.sha256 = digest
            doc.tamanho_bytes = len(response.content)

            if extract_text:
                text, paginas = extract_pdf_text(pdf_path)
                doc.paginas = paginas
                text_fname = fname.replace(".pdf", ".txt")
                text_path = text_dir / text_fname
                text_path.write_text(text, encoding="utf-8", errors="replace")
                doc.texto_path = f"texto/{text_fname}"

            docs_pdf.append(doc)
            print(f"[{idx}/{len(documentos)}] OK PDF: {doc.titulo}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            erros.append({**doc.asdict(), "erro": str(exc)})
            print(f"[{idx}/{len(documentos)}] ERRO: {doc.titulo}: {exc}", file=sys.stderr)

    return docs_pdf, nao_pdf, erros


def gerar_indices(out: Path, docs_pdf: list[Documento], nao_pdf: list[dict[str, Any]], erros: list[dict[str, Any]], fonte_url: str) -> None:
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "fonte_oficial": fonte_url,
        "data_coleta": now_iso(),
        "total_pdfs": len(docs_pdf),
        "total_links_nao_pdf_ou_ignorados": len(nao_pdf),
        "total_erros": len(erros),
        "observacao": "Use sha256 e data_coleta para auditoria. Não reproduzir normas ABNT/NBR em texto integral.",
    }

    docs_pdf_sorted = sorted(docs_pdf, key=lambda d: (d.numero_it or "999", d.titulo))
    its = [d for d in docs_pdf_sorted if d.numero_it]

    manifest = {"metadata": metadata, "documentos": [doc.asdict() for doc in docs_pdf_sorted]}
    its_manifest = {"metadata": metadata, "instrucoes_tecnicas": [doc.asdict() for doc in its]}

    salvar_json(data_dir / "normas_manifest.json", manifest)
    salvar_json(data_dir / "instrucoes_tecnicas_manifest.json", its_manifest)
    salvar_json(data_dir / "links_nao_pdf.json", {"metadata": metadata, "items": nao_pdf})
    salvar_json(data_dir / "erros_download.json", {"metadata": metadata, "items": erros})

    normas_com_texto: list[dict[str, Any]] = []
    for d in its:
        texto = ""
        if d.texto_path:
            p = out / d.texto_path
            if p.exists():
                texto = p.read_text(encoding="utf-8", errors="replace")
        normas_com_texto.append({**d.asdict(), "texto": texto})

    normas_com_texto_obj = {"metadata": metadata, "normas": normas_com_texto}
    salvar_json(data_dir / "normas_com_texto.json", normas_com_texto_obj)

    # Compatibilidade com endpoints antigos publicados na raiz do GitHub Pages (/docs).
    salvar_json(out / "normas_com_texto.json", normas_com_texto_obj)
    salvar_json(out / "normas_manifest.json", manifest)
    salvar_json(out / "instrucoes_tecnicas_manifest.json", its_manifest)

    chunks_path = data_dir / "normas_chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for d in its:
            texto = ""
            if d.texto_path:
                p = out / d.texto_path
                if p.exists():
                    texto = p.read_text(encoding="utf-8", errors="replace")
            for i, chunk in enumerate(chunk_text(texto), start=1):
                f.write(json.dumps({
                    "id": f"IT-{d.numero_it}-chunk-{i:04d}",
                    "numero_it": d.numero_it,
                    "titulo": d.titulo,
                    "categoria": d.categoria,
                    "url_pdf_oficial": d.url,
                    "sha256": d.sha256,
                    "chunk_index": i,
                    "texto": chunk,
                }, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza PDFs oficiais da página de normas técnicas do CBMMG.")
    parser.add_argument("--url", default=OFICIAL_URL, help="URL da página oficial do CBMMG.")
    parser.add_argument("--out", default="docs", help="Diretório de saída publicado pelo GitHub Pages.")
    parser.add_argument("--extract-text", action="store_true", help="Extrai texto dos PDFs baixados.")
    parser.add_argument("--allow-external", action="store_true", help="Permite baixar PDFs fora do domínio bombeiros.mg.gov.br.")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)

    session = get_session()
    html = fetch(session, args.url).text
    docs = extrair_links_da_pagina(html, args.url)

    salvar_json(out / "data" / "links_detectados_brutos.json", {
        "metadata": {"fonte_oficial": args.url, "data_coleta": now_iso(), "total_links": len(docs)},
        "links": [d.asdict() for d in docs],
    })

    docs_pdf, nao_pdf, erros = download_e_processar(
        session=session,
        documentos=docs,
        out=out,
        extract_text=args.extract_text,
        only_cbmmg_host=not args.allow_external,
    )
    gerar_indices(out, docs_pdf, nao_pdf, erros, args.url)

    print(json.dumps({"ok": True, "pdfs": len(docs_pdf), "nao_pdf": len(nao_pdf), "erros": len(erros)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sincronizador oficial - Legislação e Normas Técnicas CBMMG

Objetivo:
1) Ler a página oficial de normas técnicas do CBMMG.
2) Identificar links de PDFs por seção: leis, decretos, portarias, instruções técnicas, emendas, erratas etc.
3) Baixar os PDFs oficiais, calcular SHA-256 e gerar manifesto auditável.
4) Extrair texto pesquisável dos PDFs, com foco especial nas Instruções Técnicas vigentes.
5) Publicar arquivos JSON/JSONL estáticos para uso em GitHub Pages e Actions do Custom GPT.

Observação importante:
- Não baixe nem hospede texto integral de normas ABNT/NBR. Elas são protegidas por direitos autorais.
- Este script foi desenhado para documentos oficiais publicados no site do CBMMG.

Uso local:
    python scripts/sincronizar_normas_cbmmg.py --out public

Uso no GitHub Actions:
    python scripts/sincronizar_normas_cbmmg.py --out public --extract-text
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
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
USER_AGENT = "RWValente-CBMMG-Sync/2.0 (+GitHub Pages; educational mirror)"
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
    return value[:max_len].strip("-") or "documento"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"})
    return s


def fetch(session: requests.Session, url: str) -> requests.Response:
    last_exc: Exception | None = None
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if tentativa < MAX_RETRIES:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {last_exc}")


def is_probably_pdf(response: requests.Response, url: str) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type:
        return True
    if urlparse(url).path.lower().endswith(".pdf"):
        return True
    return response.content[:5] == b"%PDF-"


def parse_it_metadata(titulo: str, complemento: str = "") -> tuple[str | None, str | None, str | None, str | None]:
    numero_it = None
    edicao = None
    situacao = None
    alteracao = None

    m = re.search(r"\bIT\s*0*([0-9]{1,2})\b", titulo, flags=re.I)
    if m:
        numero_it = f"{int(m.group(1)):02d}"

    m = re.search(r"(\d+)\s*[ªaºo]\s*Edi[cç][aã]o", titulo, flags=re.I)
    if m:
        edicao = f"{m.group(1)}ª Edição"

    full = f"{titulo} {complemento}".strip()
    if "revogada" in full.lower():
        situacao = "revogada"
    else:
        situacao = "vigente/listada"

    m = re.search(r"\((Alterada|Aprovada|Adotar|Revogada)[^)]+\)", full, flags=re.I)
    if m:
        alteracao = m.group(0).strip("() ")

    return numero_it, edicao, situacao, alteracao


def section_name(text: str) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    clean = clean.replace("#####", "").replace("####", "").strip()
    return clean or "Sem seção"


def extrair_links_da_pagina(html: str, base_url: str) -> list[Documento]:
    soup = BeautifulSoup(html, "html.parser")

    # Tentativa de reduzir ruído: usar área de conteúdo quando existir.
    root = soup.find("main") or soup.find(id=re.compile("conteudo|content", re.I)) or soup.body or soup

    categoria_atual = "Sem seção"
    subcategoria_atual: str | None = None
    documentos: list[Documento] = []

    # Percorre a árvore em ordem visual. A página do CBMMG usa headings e listas simples.
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a", "li"], recursive=True):
        tag = el.name.lower()
        texto = re.sub(r"\s+", " ", el.get_text(" ", strip=True))

        if tag in {"h3", "h4", "h5"}:
            nome = section_name(texto)
            # Nomes numéricos como "2025" funcionam melhor como subcategoria.
            if re.fullmatch(r"20\d{2}|19\d{2}|\d{4}", nome):
                subcategoria_atual = nome
            else:
                categoria_atual = nome
                subcategoria_atual = None
            continue

        if tag == "a" and el.get("href"):
            href = urljoin(base_url, el.get("href"))
            titulo = texto
            if not titulo or titulo.lower().startswith(("ir para", "início", "facebook", "youtube", "instagram")):
                continue

            # Captura o texto do item da lista para pegar observações como "Alterada pela Portaria...".
            complemento = ""
            parent_li = el.find_parent("li")
            if parent_li:
                complemento = re.sub(r"\s+", " ", parent_li.get_text(" ", strip=True))
            else:
                complemento = titulo

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

    # Remove duplicatas por URL mantendo o primeiro registro útil.
    vistos: set[str] = set()
    unicos: list[Documento] = []
    for doc in documentos:
        if doc.url in vistos:
            continue
        vistos.add(doc.url)
        unicos.append(doc)
    return unicos


def salvar_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_text(pdf_path: Path) -> tuple[str, int | None]:
    # Preferência: PyMuPDF; fallback: pypdf.
    try:
        import fitz  # type: ignore

        texts: list[str] = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                t = page.get_text("text") or ""
                if t.strip():
                    texts.append(f"\n\n--- PÁGINA {i} ---\n{t.strip()}")
            return "".join(texts).strip(), len(doc)
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(pdf_path))
            texts = []
            for i, page in enumerate(reader.pages, start=1):
                t = page.extract_text() or ""
                if t.strip():
                    texts.append(f"\n\n--- PÁGINA {i} ---\n{t.strip()}")
            return "".join(texts).strip(), len(reader.pages)
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
        # Tenta quebrar em fim de parágrafo para ficar bonito.
        if end < n:
            break_at = text.rfind("\n\n", start, end)
            if break_at > start + int(size * 0.6):
                end = break_at
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        next_start = max(0, end - overlap)
        start = next_start if next_start > start else end
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
    data_dir = out / "data"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    docs_pdf: list[Documento] = []
    nao_pdf: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []

    for idx, doc in enumerate(documentos, start=1):
        host = urlparse(doc.url).netloc.lower()
        if only_cbmmg_host and "bombeiros.mg.gov.br" not in host:
            nao_pdf.append({**doc.asdict(), "motivo": "host externo ignorado"})
            continue

        try:
            r = fetch(session, doc.url)
            if not is_probably_pdf(r, doc.url):
                nao_pdf.append({**doc.asdict(), "motivo": "não retornou PDF", "content_type": r.headers.get("content-type")})
                continue
            digest = sha256_bytes(r.content)
            prefix = f"it-{doc.numero_it}" if doc.numero_it else slugify(doc.categoria)
            fname = f"{prefix}-{slugify(doc.titulo)}-{digest[:12]}.pdf"
            pdf_path = pdf_dir / fname
            if not pdf_path.exists() or pdf_path.read_bytes() != r.content:
                pdf_path.write_bytes(r.content)

            doc.arquivo = f"pdf/{fname}"
            doc.sha256 = digest
            doc.tamanho_bytes = len(r.content)

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
    metadata = {
        "fonte_oficial": fonte_url,
        "data_coleta": now_iso(),
        "total_pdfs": len(docs_pdf),
        "total_links_nao_pdf_ou_ignorados": len(nao_pdf),
        "total_erros": len(erros),
        "observacao": "Use sempre o campo sha256 e a data_coleta para auditoria. Não reproduzir normas ABNT/NBR em texto integral.",
    }

    manifest = {
        "metadata": metadata,
        "documentos": [doc.asdict() for doc in docs_pdf],
    }
    salvar_json(data_dir / "normas_manifest.json", manifest)
    salvar_json(data_dir / "links_nao_pdf.json", {"metadata": metadata, "items": nao_pdf})
    salvar_json(data_dir / "erros_download.json", {"metadata": metadata, "items": erros})

    its = [d for d in docs_pdf if d.numero_it]
    its.sort(key=lambda d: int(d.numero_it or 999))
    its_manifest = {"metadata": metadata, "instrucoes_tecnicas": [d.asdict() for d in its]}
    salvar_json(data_dir / "instrucoes_tecnicas_manifest.json", its_manifest)

    # JSON com texto integral das ITs vigentes/listadas. Útil para a Action listarNormasComTexto.
    normas_com_texto = []
    for d in its:
        texto = ""
        if d.texto_path:
            p = out / d.texto_path
            if p.exists():
                texto = p.read_text(encoding="utf-8", errors="replace")
        normas_com_texto.append({**d.asdict(), "texto": texto})

    normas_com_texto_obj = {"metadata": metadata, "normas": normas_com_texto}
    salvar_json(data_dir / "normas_com_texto.json", normas_com_texto_obj)

    # Compatibilidade com o endpoint antigo do GPT:
    # https://wellingtonvalente.github.io/normas-bombeiros/normas_com_texto.json
    # Quando o GitHub Pages publica /docs, este arquivo precisa existir na raiz de /docs.
    salvar_json(out / "normas_com_texto.json", normas_com_texto_obj)
    salvar_json(out / "normas_manifest.json", manifest)
    salvar_json(out / "instrucoes_tecnicas_manifest.json", its_manifest)

    # JSONL em chunks para busca sem carregar um monolito gigante.
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
    parser.add_argument("--out", default="public", help="Diretório de saída.")
    parser.add_argument("--extract-text", action="store_true", help="Extrai texto dos PDFs baixados.")
    parser.add_argument("--allow-external", action="store_true", help="Permite baixar PDFs fora do domínio bombeiros.mg.gov.br.")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
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

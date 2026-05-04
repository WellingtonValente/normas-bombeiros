#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincronizador robusto da base CBMMG para GitHub Pages.

Esta versão evita o problema de publicar JSON vazio quando a página oficial
retorna HTML sem links, muda a estrutura, ou o parser não encontra candidatos.
Ela também usa headers semelhantes a navegador e faz fallback por regex.
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
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

URLS_OFICIAIS = [
    "https://www.bombeiros.mg.gov.br/normastecnicas",
    "https://bombeiros.mg.gov.br/normastecnicas",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 RWValente-CBMMG-Sync/4.0"
)
TIMEOUT = 60
MAX_RETRIES = 3
CHUNK_SIZE_CHARS = 4500
CHUNK_OVERLAP_CHARS = 350

@dataclasses.dataclass
class Documento:
    titulo: str
    url: str
    categoria: str = "Sem seção"
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


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def salvar_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str, max_len: int = 130) -> str:
    value = unquote(value or "")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (value[:max_len].strip("-") or "documento")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.7,en;q=0.5",
        "Connection": "keep-alive",
        "Referer": "https://www.bombeiros.mg.gov.br/",
    })
    return session


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


def is_cbmmg_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("bombeiros.mg.gov.br")


def is_probably_pdf_response(response: requests.Response, url: str) -> bool:
    ctype = response.headers.get("content-type", "").lower()
    path = urlparse(response.url or url).path.lower()
    return "application/pdf" in ctype or path.endswith(".pdf") or response.content[:5] == b"%PDF-"


def titulo_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    name = re.sub(r"[_-]+", " ", name)
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    return name.strip() or url


def parse_metadata(titulo: str, url: str, contexto: str = "") -> tuple[str | None, str | None, str, str | None]:
    full = " ".join([titulo or "", unquote(url or ""), contexto or ""])
    numero_it = None
    edicao = None
    alteracao = None

    m = re.search(r"\b(?:IT|Instru[cç][aã]o\s+T[eé]cnica)\s*[_ nºn\.\-]*0*([0-9]{1,2})\b", full, flags=re.I)
    if not m:
        m = re.search(r"\bIT[_\- ]*0*([0-9]{1,2})\b", full, flags=re.I)
    if m:
        numero_it = f"{int(m.group(1)):02d}"

    m = re.search(r"(\d+)\s*[ªaºo]?\s*(?:ed|edi[cç][aã]o|edi)", full, flags=re.I)
    if m:
        edicao = f"{m.group(1)}ª Edição"

    situacao = "revogada" if "revogad" in full.lower() else "vigente/listada"

    m = re.search(r"(Portaria\s*n?[ºo]?\s*\d+/?\d*|Emenda\s*n?[ºo]?\s*\d+/?\d*)", full, flags=re.I)
    if m:
        alteracao = re.sub(r"\s+", " ", m.group(1)).strip()

    return numero_it, edicao, situacao, alteracao


def classificar_categoria(titulo: str, url: str, categoria_atual: str) -> str:
    full = f"{titulo} {url}".lower()
    if "intrucoestecnicas" in full or re.search(r"\bit[_\- ]?\d", full):
        return "Instruções Técnicas"
    if "portaria" in full:
        return "Portarias"
    if "decreto" in full:
        return "Decretos"
    if "lei" in full:
        return "Leis"
    return categoria_atual or "Outros documentos"


def link_eh_candidato(titulo: str, url: str) -> bool:
    if not is_cbmmg_url(url):
        return False
    full = f"{titulo} {unquote(url)}".lower()
    if any(x in full for x in ["tiktok", "facebook", "instagram", "youtube", "x-twitter", "intranet"]):
        return False
    return (
        ".pdf" in full
        or "/storage/files/shares/" in full
        or "portaria" in full
        or "instru" in full
        or re.search(r"\bit\s*0?\d{1,2}\b", full) is not None
        or "decreto" in full
        or re.search(r"\blei\s*\d", full) is not None
    )


def extrair_links(html: str, base_url: str) -> list[Documento]:
    soup = BeautifulSoup(html, "html.parser")
    elementos = soup.find_all(True)

    categoria_atual = "Sem seção"
    subcategoria_atual: str | None = None
    docs: list[Documento] = []

    for el in elementos:
        tag = (el.name or "").lower()
        texto = re.sub(r"\s+", " ", el.get_text(" ", strip=True) or "").strip()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if re.fullmatch(r"(?:19|20)\d{2}", texto):
                subcategoria_atual = texto
            elif texto:
                categoria_atual = texto
                subcategoria_atual = None
            continue

        if tag != "a":
            continue
        href_raw = el.get("href")
        if not href_raw:
            continue
        href = urljoin(base_url, str(href_raw))
        titulo = texto or titulo_from_url(href)
        if not link_eh_candidato(titulo, href):
            continue

        contexto = ""
        parent = el.find_parent(["li", "p", "div"])
        if parent:
            contexto = re.sub(r"\s+", " ", parent.get_text(" ", strip=True) or "").strip()
        numero_it, edicao, situacao, alteracao = parse_metadata(titulo, href, contexto)
        categoria = classificar_categoria(titulo, href, categoria_atual)
        docs.append(Documento(
            titulo=titulo,
            url=href,
            categoria=categoria,
            subcategoria=subcategoria_atual,
            numero_it=numero_it,
            edicao=edicao,
            situacao=situacao,
            alteracao=alteracao,
        ))

    # fallback por regex para hrefs PDF/storage caso o parser de anchors perca algo
    for href_raw in re.findall(r"href=[\"']([^\"']+)[\"']", html, flags=re.I):
        href = urljoin(base_url, href_raw)
        titulo = titulo_from_url(href)
        if link_eh_candidato(titulo, href):
            numero_it, edicao, situacao, alteracao = parse_metadata(titulo, href)
            categoria = classificar_categoria(titulo, href, "Outros documentos")
            docs.append(Documento(
                titulo=titulo,
                url=href,
                categoria=categoria,
                subcategoria=None,
                numero_it=numero_it,
                edicao=edicao,
                situacao=situacao,
                alteracao=alteracao,
            ))

    unicos: dict[str, Documento] = {}
    for d in docs:
        # Remova fragmentos e normalize URL para evitar duplicidade.
        parsed = urlparse(d.url)
        clean = parsed._replace(fragment="").geturl()
        if clean not in unicos:
            d.url = clean
            unicos[clean] = d
        else:
            # preserva título mais informativo se apareceu depois
            if len(d.titulo) > len(unicos[clean].titulo):
                unicos[clean].titulo = d.titulo
    return list(unicos.values())


def escolher_pagina(session: requests.Session, urls: list[str], debug_dir: Path) -> tuple[str, str, dict[str, Any]]:
    melhor_url = urls[0]
    melhor_html = ""
    diagnosticos: list[dict[str, Any]] = []
    melhor_total = -1

    for url in urls:
        r = fetch(session, url)
        html = r.text
        docs = extrair_links(html, r.url or url)
        diag = {
            "url_solicitada": url,
            "url_final": r.url,
            "status_code": r.status_code,
            "content_type": r.headers.get("content-type"),
            "html_length": len(html),
            "links_candidatos": len(docs),
        }
        diagnosticos.append(diag)
        (debug_dir / f"debug_html_{slugify(url)}.html").write_text(html, encoding="utf-8", errors="replace")
        if len(docs) > melhor_total:
            melhor_total = len(docs)
            melhor_url = r.url or url
            melhor_html = html

    return melhor_url, melhor_html, {"tentativas": diagnosticos, "melhor_total_links": melhor_total}


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
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
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


def baixar_processar(session: requests.Session, documentos: list[Documento], out: Path, extract_text: bool, allow_external: bool) -> tuple[list[Documento], list[dict[str, Any]], list[dict[str, Any]]]:
    pdf_dir = out / "pdf"
    text_dir = out / "texto"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    docs_pdf: list[Documento] = []
    nao_pdf: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []

    for idx, doc in enumerate(documentos, start=1):
        if not allow_external and not is_cbmmg_url(doc.url):
            nao_pdf.append({**doc.asdict(), "motivo": "host externo ignorado"})
            continue
        try:
            r = fetch(session, doc.url)
            if not is_probably_pdf_response(r, doc.url):
                nao_pdf.append({**doc.asdict(), "motivo": "não retornou PDF", "content_type": r.headers.get("content-type"), "url_final": r.url})
                continue
            digest = sha256_bytes(r.content)
            prefix = f"it-{doc.numero_it}" if doc.numero_it else slugify(doc.categoria)
            fname = f"{prefix}-{slugify(doc.titulo)}-{digest[:12]}.pdf"
            pdf_path = pdf_dir / fname
            if not pdf_path.exists() or pdf_path.read_bytes() != r.content:
                pdf_path.write_bytes(r.content)
            doc.url = r.url or doc.url
            doc.arquivo = f"pdf/{fname}"
            doc.sha256 = digest
            doc.tamanho_bytes = len(r.content)
            if extract_text:
                text, paginas = extract_pdf_text(pdf_path)
                doc.paginas = paginas
                txt_name = fname.replace(".pdf", ".txt")
                txt_path = text_dir / txt_name
                txt_path.write_text(text, encoding="utf-8", errors="replace")
                doc.texto_path = f"texto/{txt_name}"
            docs_pdf.append(doc)
            print(f"[{idx}/{len(documentos)}] OK PDF: {doc.titulo}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            erros.append({**doc.asdict(), "erro": str(exc)})
            print(f"[{idx}/{len(documentos)}] ERRO: {doc.titulo}: {exc}", file=sys.stderr)
    return docs_pdf, nao_pdf, erros


def gerar_indices(out: Path, docs_pdf: list[Documento], nao_pdf: list[dict[str, Any]], erros: list[dict[str, Any]], fonte_url: str, diagnostico: dict[str, Any]) -> None:
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "fonte_oficial": fonte_url,
        "data_coleta": now_iso(),
        "total_pdfs": len(docs_pdf),
        "total_links_nao_pdf_ou_ignorados": len(nao_pdf),
        "total_erros": len(erros),
        "diagnostico_coleta": diagnostico,
        "observacao": "Use sha256 e data_coleta para auditoria. Não reproduzir normas ABNT/NBR em texto integral.",
    }
    docs_pdf_sorted = sorted(docs_pdf, key=lambda d: (d.numero_it or "999", d.categoria, d.titulo))
    its = [d for d in docs_pdf_sorted if d.numero_it]
    manifest = {"metadata": metadata, "documentos": [d.asdict() for d in docs_pdf_sorted]}
    its_manifest = {"metadata": metadata, "instrucoes_tecnicas": [d.asdict() for d in its]}
    salvar_json(data_dir / "normas_manifest.json", manifest)
    salvar_json(data_dir / "instrucoes_tecnicas_manifest.json", its_manifest)
    salvar_json(data_dir / "links_nao_pdf.json", {"metadata": metadata, "items": nao_pdf})
    salvar_json(data_dir / "erros_download.json", {"metadata": metadata, "items": erros})

    normas: list[dict[str, Any]] = []
    for d in its:
        texto = ""
        if d.texto_path:
            p = out / d.texto_path
            if p.exists():
                texto = p.read_text(encoding="utf-8", errors="replace")
        normas.append({**d.asdict(), "texto": texto})
    normas_obj = {"metadata": metadata, "normas": normas}
    salvar_json(data_dir / "normas_com_texto.json", normas_obj)
    salvar_json(out / "normas_com_texto.json", normas_obj)
    salvar_json(out / "normas_manifest.json", manifest)
    salvar_json(out / "instrucoes_tecnicas_manifest.json", its_manifest)

    with (data_dir / "normas_chunks.jsonl").open("w", encoding="utf-8") as f:
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
    parser.add_argument("--url", default=None, help="URL da página oficial do CBMMG. Se omitida, testa com e sem www.")
    parser.add_argument("--out", default="docs", help="Diretório de saída publicado pelo GitHub Pages.")
    parser.add_argument("--extract-text", action="store_true", help="Extrai texto dos PDFs baixados.")
    parser.add_argument("--allow-external", action="store_true", help="Permite baixar PDFs fora do domínio bombeiros.mg.gov.br.")
    parser.add_argument("--no-fail-if-empty", action="store_true", help="Não falha quando nenhum PDF for encontrado. Não recomendado.")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    debug_dir = out / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    session = get_session()
    urls = [args.url] if args.url else URLS_OFICIAIS
    fonte_url, html, diagnostico = escolher_pagina(session, [u for u in urls if u], debug_dir)
    docs = extrair_links(html, fonte_url)
    salvar_json(out / "data" / "links_detectados_brutos.json", {
        "metadata": {"fonte_oficial": fonte_url, "data_coleta": now_iso(), "total_links": len(docs), **diagnostico},
        "links": [d.asdict() for d in docs],
    })

    if not docs:
        msg = {
            "ok": False,
            "motivo": "Nenhum link candidato encontrado na página oficial. HTML de diagnóstico salvo em docs/debug.",
            "diagnostico": diagnostico,
        }
        print(json.dumps(msg, ensure_ascii=False, indent=2))
        return 2 if not args.no_fail_if_empty else 0

    docs_pdf, nao_pdf, erros = baixar_processar(session, docs, out, args.extract_text, args.allow_external)

    if not docs_pdf:
        salvar_json(out / "data" / "links_nao_pdf.json", {"metadata": {"fonte_oficial": fonte_url, "data_coleta": now_iso()}, "items": nao_pdf})
        salvar_json(out / "data" / "erros_download.json", {"metadata": {"fonte_oficial": fonte_url, "data_coleta": now_iso()}, "items": erros})
        msg = {
            "ok": False,
            "motivo": "Links foram encontrados, mas nenhum retornou PDF. Não vou sobrescrever manifestos com base vazia.",
            "links_detectados": len(docs),
            "nao_pdf": len(nao_pdf),
            "erros": len(erros),
            "diagnostico": diagnostico,
        }
        print(json.dumps(msg, ensure_ascii=False, indent=2))
        return 3 if not args.no_fail_if_empty else 0

    gerar_indices(out, docs_pdf, nao_pdf, erros, fonte_url, diagnostico)
    print(json.dumps({
        "ok": True,
        "fonte_url": fonte_url,
        "links_detectados": len(docs),
        "pdfs": len(docs_pdf),
        "nao_pdf": len(nao_pdf),
        "erros": len(erros),
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

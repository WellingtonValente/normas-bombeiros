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
import shutil
import sys
import tempfile
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
TIMEOUT = (10, 30)  # Limites distintos de conexão e leitura, por tentativa.
MAX_RETRIES = 2
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
    data_coleta: str | None = None
    coleta_estado: str | None = None
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
        except requests.RequestException as exc:
            last_exc = exc
            # Repetir um 404/403 não resolve a coleta; tente a próxima origem.
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                    break
            if tentativa < MAX_RETRIES:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {last_exc}")


def is_cbmmg_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in {
        "bombeiros.mg.gov.br", "www.bombeiros.mg.gov.br",
    }


def is_nonproduction_cbmmg_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".bombeiros.mg.gov.br") and host != "www.bombeiros.mg.gov.br"


def is_probably_pdf_response(response: requests.Response, url: str) -> bool:
    # Extensão e Content-Type podem acompanhar uma página HTML de erro.
    # Não aceitar esses sinais como prova do formato recebido.
    return response.content.startswith(b"%PDF-")


def fetch_document(session: requests.Session, url: str) -> requests.Response:
    urls = [url]
    if is_cbmmg_url(url):
        parsed = urlparse(url)
        alternate = "bombeiros.mg.gov.br" if parsed.hostname == "www.bombeiros.mg.gov.br" else "www.bombeiros.mg.gov.br"
        urls.append(parsed._replace(netloc=alternate).geturl())
    last_exc: Exception | None = None
    for candidate in urls:
        try:
            result = fetch(session, candidate)
            if urlparse(url).path.lower().endswith(".pdf") and not is_probably_pdf_response(result, url):
                raise ValueError("Documento esperado como PDF sem assinatura %PDF-.")
            return result
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            last_exc = exc
    raise RuntimeError(f"Nenhuma origem de produção forneceu o documento {url}: {last_exc}")


def titulo_from_url(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    name = re.sub(r"[_-]+", " ", name)
    name = re.sub(r"\.pdf$", "", name, flags=re.I)
    return name.strip() or url


def parse_metadata(titulo: str, url: str, contexto: str = "") -> tuple[str | None, str | None, str, str | None]:
    # Identidade vem exclusivamente do próprio link. Um contêiner HTML pode
    # mencionar dezenas de outras ITs ou a revogação de outra edição.
    full = " ".join([titulo or "", titulo_from_url(url or "")])
    full = re.sub(r"[_]+", " ", full)
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

    situacao = "nao_verificada"
    # Contexto só informa estado quando o chamador isolou uma anotação curta.
    # Não usar o caminho da URL, nem verbos como 'revoga', para inferir vigência.
    sinais = re.sub(r"\s+", " ", titulo or "").strip()
    contexto = re.sub(r"\s+", " ", contexto or "").strip()
    if contexto and len(contexto) <= 100 and re.fullmatch(
        r"[\s()\[\]:;,.\-]*(?:(?:situa[cç][aã]o|status)\s*:\s*)?"
        r"(?:revogad[ao]|vigente|em vigor|minuta|consulta p[uú]blica|"
        r"em consulta p[uú]blica)[\s()\[\]:;,.\-]*", contexto, flags=re.I,
    ):
        sinais += " " + contexto
    if re.search(r"\b(?:minuta|(?:em\s+)?consulta\s+p[uú]blica)\b", sinais, re.I):
        situacao = "consulta_publica"
    elif re.search(r"\brevogad[ao]\b", sinais, re.I) and not re.search(
        r"\b(?:n[aã]o|parcialmente)\s+revogad[ao]\b|\brevogad[ao]\s+parcialmente\b", sinais, re.I,
    ):
        situacao = "revogada"
    elif re.search(r"\b(?:vigente|em\s+vigor)\b", sinais, re.I) and not re.search(
        r"\bn[aã]o\s+(?:vigente|em\s+vigor)\b", sinais, re.I,
    ):
        situacao = "listada_como_vigente"

    m = re.search(r"((?:Portaria|Emenda)\s*n?[ºo]?\s*\d+(?:[ /]+\d{4})?)", full, flags=re.I)
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
        parent = el.find_parent(["li", "p", "td"])
        if parent and len(parent.find_all("a")) == 1:
            parent_text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True) or "").strip()
            # Somente a anotação residual, se for um rótulo inequívoco.
            contexto = parent_text.replace(texto, "", 1).strip() if texto else ""
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
    melhor_url = ""
    melhor_html = ""
    diagnosticos: list[dict[str, Any]] = []
    melhor_total = -1

    debug_dir.mkdir(parents=True, exist_ok=True)
    for url in urls:
        try:
            if not is_cbmmg_url(url):
                raise ValueError("A página de origem precisa ser do portal oficial de produção do CBMMG.")
            r = fetch(session, url)
            if not is_cbmmg_url(r.url or url):
                raise ValueError("Redirecionamento da página para origem não validada.")
            html = r.text
            docs = extrair_links(html, r.url or url)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            diagnosticos.append({"url_solicitada": url, "erro": str(exc)})
            continue
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
        if is_nonproduction_cbmmg_url(doc.url):
            erros.append({**doc.asdict(), "erro": "Origem CBMMG fora do portal de produção; requer validação humana."})
            continue
        if not allow_external and not is_cbmmg_url(doc.url):
            nao_pdf.append({**doc.asdict(), "motivo": "host externo ignorado"})
            continue
        try:
            r = fetch_document(session, doc.url)
            final_url = r.url or doc.url
            if is_nonproduction_cbmmg_url(final_url) or (not allow_external and not is_cbmmg_url(final_url)):
                raise ValueError("Redirecionamento do documento para origem não validada.")
            if not is_probably_pdf_response(r, doc.url):
                detalhe = {**doc.asdict(), "motivo": "não retornou PDF", "content_type": r.headers.get("content-type"), "url_final": r.url}
                if urlparse(doc.url).path.lower().endswith(".pdf") or "application/pdf" in r.headers.get("content-type", "").lower():
                    erros.append({**detalhe, "erro": "Documento esperado como PDF sem assinatura %PDF-."})
                else:
                    nao_pdf.append(detalhe)
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
                if paginas is None or text.startswith("[ERRO DE EXTRAÇÃO:"):
                    raise ValueError("Falha ao extrair o PDF; a versão publicada será preservada.")
                doc.paginas = paginas
                txt_name = fname.replace(".pdf", ".txt")
                txt_path = text_dir / txt_name
                txt_path.write_text(text, encoding="utf-8", errors="replace")
                doc.texto_path = f"texto/{txt_name}"
            doc.data_coleta = now_iso()
            doc.coleta_estado = "coletado"
            docs_pdf.append(doc)
            print(f"[{idx}/{len(documentos)}] OK PDF: {doc.titulo}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            erros.append({**doc.asdict(), "erro": str(exc)})
            print(f"[{idx}/{len(documentos)}] ERRO: {doc.titulo}: {exc}", file=sys.stderr)
    return docs_pdf, nao_pdf, erros


def gerar_indices(out: Path, docs_pdf: list[Documento], nao_pdf: list[dict[str, Any]], erros: list[dict[str, Any]], fonte_url: str, diagnostico: dict[str, Any], *, coleta_completa: bool = True, data_coleta_anterior: str | None = None) -> None:
    if not docs_pdf or (coleta_completa and erros):
        raise ValueError("Não é permitido promover uma coleta vazia ou declarar completa uma coleta com erros.")
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "fonte_oficial": fonte_url,
        "data_coleta": now_iso() if coleta_completa else data_coleta_anterior,
        "coleta_completa": coleta_completa,
        "total_pdfs": len(docs_pdf),
        "total_links_nao_pdf_ou_ignorados": len(nao_pdf),
        "total_erros": len(erros),
        "diagnostico_coleta": diagnostico,
        "observacao": "Data de coleta não comprova vigência. 'listada_como_vigente' registra apenas o rótulo da página; confirme o ato normativo e as alterações aplicáveis. Use sha256 para auditoria. Não reproduzir normas ABNT/NBR em texto integral.",
    }
    if not coleta_completa:
        metadata["ultima_coleta_parcial"] = now_iso()
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


def chave_url(url: str) -> str:
    """Os dois hosts oficiais representam a mesma identidade de documento."""
    parsed = urlparse(url)
    host = parsed.netloc
    if parsed.hostname in {"www.bombeiros.mg.gov.br", "bombeiros.mg.gov.br"}:
        host = "bombeiros.mg.gov.br"
    return parsed._replace(netloc=host, fragment="").geturl()


def ler_json_existente(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON inválido em {path.name}: objeto esperado.")
    return value


def preservar_documentos(anterior: dict[str, Any], coletados: list[Documento], out: Path, staged: Path) -> list[Documento]:
    """Mescla sucessos com a base histórica; ausência não é revogação."""
    result = {chave_url(doc.url): doc for doc in coletados}
    fields = {field.name for field in dataclasses.fields(Documento)}
    # Repositórios antigos guardam o texto somente no JSON consolidado.
    corpus_path = out / "data" / "normas_com_texto.json"
    if not corpus_path.exists():
        corpus_path = out / "normas_com_texto.json"
    corpus = ler_json_existente(corpus_path)
    texts = {chave_url(item["url"]): item.get("texto", "") for item in corpus.get("normas", [])
        if isinstance(item, dict) and item.get("url")}
    for record in anterior.get("documentos", []):
        if not record.get("url") or chave_url(record["url"]) in result:
            continue
        values = {key: value for key, value in record.items() if key in fields}
        values.setdefault("titulo", titulo_from_url(record["url"]))
        doc = Documento(**values)
        doc.data_coleta = doc.data_coleta or anterior.get("metadata", {}).get("data_coleta")
        doc.coleta_estado = "preservado_sem_nova_coleta"
        if doc.situacao in {None, "vigente/listada"}:
            doc.situacao = "nao_verificada"
        copied = False
        if doc.texto_path:
            source = (out / doc.texto_path).resolve()
            if not source.is_relative_to(out):
                raise ValueError("Caminho de texto anterior fora do diretório da base.")
            if source.exists():
                destination = staged / doc.texto_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied = True
        if not copied and texts.get(chave_url(doc.url)):
            text_path = doc.texto_path or f"texto/preservado-{sha256_bytes(doc.url.encode())[:16]}.txt"
            destination = (staged / text_path).resolve()
            if not destination.is_relative_to(staged):
                raise ValueError("Caminho de texto preservado fora da área temporária.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(texts[chave_url(doc.url)], encoding="utf-8")
            doc.texto_path = text_path
        result[chave_url(doc.url)] = doc
    return list(result.values())


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

    status: dict[str, Any] = {
        "ok": False,
        "status": "falha",
        "ultima_tentativa": now_iso(),
        "ultima_coleta_bem_sucedida": None,
        "data_coleta_base": None,
        "fonte_url": None,
        "motivo": "Coleta iniciada; promoção ainda não concluída.",
        "contagens": {},
        "diagnostico": {},
        "erros": [],
    }
    status_path = out / "data" / "sync_status.json"

    def concluir(code: int, motivo: str) -> int:
        status["motivo"] = motivo
        status["concluida_em"] = now_iso()
        salvar_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return code

    try:
        manifest_path = out / "data" / "normas_manifest.json"
        if not manifest_path.exists():
            manifest_path = out / "normas_manifest.json"
        anterior = ler_json_existente(manifest_path)
        old_status = ler_json_existente(status_path)
        metadata_anterior = anterior.get("metadata", {})
        status["data_coleta_base"] = metadata_anterior.get("data_coleta")
        status["ultima_coleta_bem_sucedida"] = old_status.get("ultima_coleta_bem_sucedida")
        if not status["ultima_coleta_bem_sucedida"] and metadata_anterior.get("total_erros") == 0:
            status["ultima_coleta_bem_sucedida"] = metadata_anterior.get("data_coleta")
        # Registrar o início permite detectar também uma interrupção/timeout.
        salvar_json(status_path, status)
        session = get_session()
        urls = [args.url] if args.url else URLS_OFICIAIS
        fonte_url, html, diagnostico = escolher_pagina(session, [u for u in urls if u], debug_dir)
        status.update(fonte_url=fonte_url or None, diagnostico=diagnostico)
        docs = extrair_links(html, fonte_url) if html else []
        status["contagens"]["links_detectados"] = len(docs)
        salvar_json(out / "data" / "links_detectados_brutos.json", {
            "metadata": {"fonte_oficial": fonte_url, "data_tentativa": status["ultima_tentativa"], "total_links": len(docs), **diagnostico},
            "links": [d.asdict() for d in docs],
        })
        if not docs:
            return concluir(0 if args.no_fail_if_empty else 2,
                "Nenhum link candidato válido na origem oficial. A base publicada foi preservada.")

        # Falhas parciais não devem alterar arquivos que alimentam o GPT.
        with tempfile.TemporaryDirectory(prefix="cbmmg-sync-") as temp_dir:
            staged = Path(temp_dir)
            docs_pdf, nao_pdf, erros = baixar_processar(session, docs, staged, args.extract_text, args.allow_external)
            old_urls = {chave_url(d["url"]) for d in anterior.get("documentos", []) if d.get("url")}
            new_urls = {chave_url(d.url) for d in docs_pdf}
            missing = sorted(old_urls - new_urls)
            status["erros"] = erros
            status["documentos_anteriores_ausentes"] = missing
            status["contagens"].update(pdfs=len(docs_pdf), nao_pdf=len(nao_pdf), erros=len(erros),
                documentos_anteriores=len(old_urls), documentos_anteriores_ausentes=len(missing))
            if not docs_pdf:
                return concluir(0 if args.no_fail_if_empty else 3,
                    "Nenhum PDF válido coletado. A base publicada foi preservada.")
            parcial = bool(erros or missing)
            merged = preservar_documentos(anterior, docs_pdf, out, staged) if parcial else docs_pdf
            status["promocao_parcial"] = parcial
            status["contagens"]["documentos_preservados"] = len(merged) - len(docs_pdf)
            # Preparar todos os índices antes de copiar qualquer artefato final.
            gerar_indices(staged, merged, nao_pdf, erros, fonte_url, diagnostico,
                coleta_completa=not parcial, data_coleta_anterior=status["data_coleta_base"])
            # Uma extração malsucedida pode deixar um PDF na área temporária.
            # Promover somente ativos referenciados por documentos aceitos.
            files_to_promote = set((staged / "data").glob("*")) | set(staged.glob("*.json"))
            for doc in merged:
                for asset in (doc.arquivo, doc.texto_path):
                    if asset:
                        source = (staged / asset).resolve()
                        if not source.is_relative_to(staged):
                            raise ValueError("Ativo fora da área temporária de coleta.")
                        if source.is_file():
                            files_to_promote.add(source)
            for source in sorted(files_to_promote):
                destination = out / source.relative_to(staged)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            publicado = ler_json_existente(out / "data" / "normas_manifest.json")
            coleta = publicado["metadata"]["data_coleta"]
            if parcial:
                return concluir(4,
                    "Coleta parcial: PDFs obtidos foram atualizados individualmente; documentos ausentes ou com erro e a data da última coleta geral foram preservados. Ausência não indica revogação.")
            status.update(ok=True, status="ok", ultima_coleta_bem_sucedida=coleta, data_coleta_base=coleta)
            return concluir(0, "Coleta completa promovida; vigência normativa deve ser confirmada por documento.")
    except Exception as exc:  # Falha operacional também precisa de diagnóstico persistente.
        status["erros"].append({"erro": str(exc), "tipo": type(exc).__name__})
        return concluir(5, "Falha operacional. Verifique o diagnóstico antes de promover alterações.")

if __name__ == "__main__":
    raise SystemExit(main())

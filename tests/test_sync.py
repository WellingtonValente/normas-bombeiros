"""Regressões de coleta/publicação; nenhuma requisição de rede é permitida."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sincronizar_normas_cbmmg.py"
SPEC = importlib.util.spec_from_file_location("cbmmg_sync", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)

OFFICIAL = "https://bombeiros.mg.gov.br/normastecnicas"
PDF_URL = "https://bombeiros.mg.gov.br/storage/files/shares/IT_01.pdf"
HTML = f'<h2>Instruções Técnicas</h2><p><a href="{PDF_URL}">IT 01 - 10ª Edição</a></p>'
OLD_DATE = "2026-05-04T20:36:47+00:00"


def response(url, data, content_type="text/html", status=200):
    result = requests.Response()
    result.status_code = status
    result.url = url
    result._content = data.encode() if isinstance(data, str) else data
    result.encoding = "utf-8"
    result.headers["content-type"] = content_type
    return result


class SourceTests(unittest.TestCase):
    def test_transport_failure_has_phase_and_attempt_history(self):
        session = Mock()
        session.get.side_effect = requests.ConnectTimeout("conexão excedeu o limite")
        with patch.object(sync.time, "sleep"):
            with self.assertRaises(sync.FetchError) as caught:
                sync.fetch(session, OFFICIAL)
        self.assertEqual(len(caught.exception.attempts), sync.MAX_RETRIES)
        self.assertTrue(all(a["fase"] == "timeout_conexao" and a["status_code"] is None
            for a in caught.exception.attempts))
        self.assertIsInstance(caught.exception.__cause__, requests.ConnectTimeout)

    def test_read_timeout_is_distinct_from_connect_timeout(self):
        self.assertEqual(sync.tipo_falha(requests.ReadTimeout()), "timeout_leitura")
        self.assertEqual(sync.tipo_falha(requests.exceptions.SSLError()), "erro_tls")

    def test_success_preserves_previous_failed_attempt_and_html_hash(self):
        session = Mock()
        session.get.side_effect = [requests.ConnectTimeout("transitório"), response(OFFICIAL, HTML)]
        with tempfile.TemporaryDirectory() as directory, patch.object(sync.time, "sleep"):
            _, _, diagnostic = sync.escolher_pagina(session, [OFFICIAL], Path(directory))
            saved = next(Path(directory).glob("*.html")).read_bytes()
        attempt = diagnostic["tentativas"][0]
        self.assertEqual(attempt["sha256_html"], sync.sha256_bytes(saved))
        self.assertEqual([a.get("fase") for a in attempt["requisicoes"]], ["timeout_conexao", None])

    def test_timeout_www_falls_back_to_production_without_www(self):
        session = Mock()

        def get(url, **kwargs):
            if "www." in url:
                raise requests.Timeout("timeout de teste")
            return response(url, HTML)

        session.get.side_effect = get
        with tempfile.TemporaryDirectory() as directory, patch.object(sync.time, "sleep"):
            url, html, diagnostic = sync.escolher_pagina(session, sync.URLS_OFICIAIS, Path(directory))
        self.assertEqual(url, OFFICIAL)
        self.assertEqual(html, HTML)
        self.assertEqual(session.get.call_count, sync.MAX_RETRIES + 1)
        self.assertIn("erro", diagnostic["tentativas"][0])
        self.assertEqual(diagnostic["melhor_total_links"], 1)

    def test_redirect_to_homologation_is_never_selected(self):
        session = Mock()
        session.get.return_value = response("https://hml.bombeiros.mg.gov.br/normastecnicas", HTML)
        with tempfile.TemporaryDirectory() as directory:
            url, html, diagnostic = sync.escolher_pagina(session, [OFFICIAL], Path(directory))
        self.assertEqual((url, html), ("", ""))
        self.assertIn("não validada", diagnostic["tentativas"][0]["erro"])

    def test_homologation_and_lookalike_hosts_are_rejected(self):
        for url in (
            "https://hml.bombeiros.mg.gov.br/normastecnicas",
            "https://evilbombeiros.mg.gov.br/file.pdf",
            "https://bombeiros.mg.gov.br.example.com/file.pdf",
            "http://bombeiros.mg.gov.br/file.pdf",
        ):
            self.assertFalse(sync.is_cbmmg_url(url), url)

    def test_404_is_not_retried(self):
        session = Mock()
        session.get.return_value = response(PDF_URL, "não encontrado", status=404)
        with patch.object(sync.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                sync.fetch(session, PDF_URL)
        self.assertEqual(session.get.call_count, 1)
        sleep.assert_not_called()


class MetadataTests(unittest.TestCase):
    def test_entities_are_decoded_once_without_phantom_regex_links(self):
        html = '''<h2>Instruções Técnicas</h2>
        <p><a href="/storage/IT_33_4&ordf;_edi&ccedil;&atilde;o.pdf">IT 33</a></p>
        <p><a href='/storage/IT_33_4ª_edição.pdf'>IT 33 - 4ª Edição</a></p>
        <p><a href="/download.pdf?a=1&amp;b=2">Documento</a></p>
        <script>const exemplo = '<a href="/falso.pdf">Exemplo</a>';</script>
        <!-- <a href="/comentario.pdf">Comentário</a> -->'''
        docs = sync.extrair_links(html, OFFICIAL)
        self.assertEqual(len(docs), 2)
        self.assertTrue(docs[0].url.endswith('/IT_33_4ª_edição.pdf'))
        self.assertTrue(docs[1].url.endswith('/download.pdf?a=1&b=2'))

    def test_encoded_path_and_official_alias_are_one_identity(self):
        html = '<a href="https://www.bombeiros.mg.gov.br/IT 01.pdf">IT 01</a>'
        html += '<a href="https://bombeiros.mg.gov.br/IT%2001.pdf">IT 01</a>'
        self.assertEqual(len(sync.extrair_links(html, OFFICIAL)), 1)
        self.assertNotEqual(sync.chave_url(OFFICIAL + '/a%2Fb'), sync.chave_url(OFFICIAL + '/a/b'))

    def test_amendment_annotation_is_retained_without_claiming_validity(self):
        html = '<p><a href="/IT_03.pdf">IT 03 - 2ª Edição</a> (Alterada pelas Portarias 83/2026 e 84/2026)</p>'
        doc = sync.extrair_links(html, OFFICIAL)[0]
        self.assertEqual(doc.anotacao_indice, '(Alterada pelas Portarias 83/2026 e 84/2026)')
        self.assertEqual(doc.situacao, 'nao_verificada')
        self.assertEqual(doc.url_listada, doc.url)

    def test_listing_does_not_prove_validity(self):
        number, edition, status, amendment = sync.parse_metadata(
            "IT 01 - Procedimentos Administrativos - 10ª Edição", PDF_URL,
        )
        self.assertEqual((number, edition, status), ("01", "10ª Edição", "nao_verificada"))

    def test_parent_does_not_leak_number_edition_or_status(self):
        result = sync.parse_metadata("Baixar documento", "https://bombeiros.mg.gov.br/documento.pdf",
            "IT 33 - 5ª Edição revogada. Consulta pública de IT 30; Portaria 99/2026")
        self.assertEqual(result, (None, None, "nao_verificada", None))

    def test_adjacent_links_do_not_inherit_revocation(self):
        html = '<div>IT 30 revogada<p><a href="/a.pdf">IT 01</a> <a href="/b.pdf">IT 02 revogada</a></p></div>'
        docs = sync.extrair_links(html, OFFICIAL)
        self.assertEqual([(d.numero_it, d.situacao) for d in docs], [("01", "nao_verificada"), ("02", "revogada")])

    def test_scoped_annotation_is_used_but_not_a_revocation_of_another_it(self):
        html = '<p><a href="/a.pdf">IT 01</a> (Revogada)</p><p><a href="/b.pdf">IT 02</a> revoga IT 03</p>'
        docs = sync.extrair_links(html, OFFICIAL)
        self.assertEqual([d.situacao for d in docs], ["revogada", "nao_verificada"])

    def test_explicit_listing_statuses_are_conservative(self):
        examples = {
            "IT 01 (Vigente)": "listada_como_vigente",
            "IT 01 em consulta pública": "consulta_publica",
            "Minuta de IT 01": "consulta_publica",
            "IT 01 não revogada": "nao_verificada",
            "IT 01 parcialmente revogada": "nao_verificada",
            "IT 01 não vigente": "nao_verificada",
        }
        for title, expected in examples.items():
            self.assertEqual(sync.parse_metadata(title, PDF_URL)[2], expected, title)

    def test_filename_is_scoped_and_supports_underscores(self):
        result = sync.parse_metadata("Documento", "https://bombeiros.mg.gov.br/IT_30/IT_01_10a_Ed_Portaria_80_2026.pdf")
        self.assertEqual(result, ("01", "10ª Edição", "nao_verificada", "Portaria 80 2026"))


class DownloadTests(unittest.TestCase):
    def test_document_download_uses_production_alias_after_timeout(self):
        session = Mock()
        def get(url, **kwargs):
            if "www." in url:
                raise requests.Timeout("www indisponível")
            return response(url, b"%PDF-1.7", "application/pdf")
        session.get.side_effect = get
        with patch.object(sync.time, "sleep"):
            result = sync.fetch_document(session, PDF_URL.replace("://", "://www."))
        self.assertEqual(result.url, PDF_URL)
        self.assertEqual(session.get.call_count, sync.MAX_RETRIES + 1)

    def test_pdf_magic_required_even_with_extension_and_mime(self):
        html = response(PDF_URL, "<!DOCTYPE html><html>erro</html>", "application/pdf")
        self.assertFalse(sync.is_probably_pdf_response(html, PDF_URL))
        pdf = response("https://bombeiros.mg.gov.br/download", b"%PDF-1.7\n", "application/octet-stream")
        self.assertTrue(sync.is_probably_pdf_response(pdf, pdf.url))

    def test_html_at_pdf_url_is_an_error_not_a_success(self):
        session = Mock()
        session.get.return_value = response(PDF_URL, "<html>bloqueado</html>")
        with tempfile.TemporaryDirectory() as directory:
            docs, ignored, errors = sync.baixar_processar(session,
                [sync.Documento("IT 01", PDF_URL)], Path(directory), False, False)
            self.assertEqual(list(Path(directory).glob("pdf/*")), [])
        self.assertEqual((len(docs), len(ignored), len(errors)), (0, 0, 1))

    def test_legitimate_navigation_link_is_not_an_error(self):
        url = "https://bombeiros.mg.gov.br/instrucoes"
        session = Mock()
        session.get.return_value = response(url, "<html>Índice</html>")
        with tempfile.TemporaryDirectory() as directory:
            docs, ignored, errors = sync.baixar_processar(session,
                [sync.Documento("Instruções", url)], Path(directory), False, False)
        self.assertEqual((len(docs), len(ignored), len(errors)), (0, 1, 0))

    def test_extraction_failure_blocks_document(self):
        session = Mock()
        session.get.return_value = response(PDF_URL, b"%PDF-corrompido", "application/pdf")
        with tempfile.TemporaryDirectory() as directory, patch.object(sync, "extract_pdf_text", return_value=("[ERRO DE EXTRAÇÃO: inválido]", None)):
            docs, _, errors = sync.baixar_processar(session,
                [sync.Documento("IT 01", PDF_URL)], Path(directory), True, False)
        self.assertEqual((len(docs), len(errors)), (0, 1))

    def test_redirect_to_homologation_blocked_even_with_allow_external(self):
        session = Mock()
        session.get.return_value = response("https://hml.bombeiros.mg.gov.br/file.pdf", b"%PDF-1.7", "application/pdf")
        with tempfile.TemporaryDirectory() as directory:
            docs, _, errors = sync.baixar_processar(session,
                [sync.Documento("IT 01", PDF_URL)], Path(directory), False, True)
        self.assertEqual((len(docs), len(errors)), (0, 1))


    def test_historical_redirect_to_external_blocked_even_with_matching_hash_and_allow_external(self):
        content = b"%PDF-1.7"
        session = Mock()
        session.get.return_value = response("https://example.com/file.pdf", content, "application/pdf")
        with tempfile.TemporaryDirectory() as directory:
            docs, _, errors = sync.baixar_processar(session,
                [sync.Documento("IT 01", PDF_URL, sha256_esperado=sync.sha256_bytes(content))],
                Path(directory), False, True)
            self.assertEqual(list(Path(directory).glob("pdf/*")), [])
        self.assertEqual((len(docs), len(errors)), (0, 1))


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name) / "docs"
        self.historicos = Path(self.directory.name) / "historicos.json"
        sync.salvar_json(self.historicos, {"versao": 1, "documentos": []})
        config_patch = patch.object(sync, "HISTORICOS_CONFIG", self.historicos)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.manifest = {
            "metadata": {"data_coleta": OLD_DATE, "total_erros": 0},
            "documentos": [{"url": PDF_URL, "numero_it": "01"}],
        }
        sync.salvar_json(self.out / "data" / "normas_manifest.json", self.manifest)
        sync.salvar_json(self.out / "normas_com_texto.json", {"normas": ["base anterior"]})

    def run_main(self, html=HTML, pdf=b"%PDF-1.7\n", extra_args=()):
        session = Mock()
        def get(url, **kwargs):
            if url == OFFICIAL:
                return response(url, html)
            return response(url, pdf, "application/pdf")
        session.get.side_effect = get
        with patch.object(sync, "get_session", return_value=session), patch.object(sys, "argv", [
            str(SCRIPT), "--url", OFFICIAL, "--out", str(self.out), *extra_args,
        ]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = sync.main()
        status = json.loads((self.out / "data" / "sync_status.json").read_text())
        return code, status

    def register_historical(self):
        old_url = "https://bombeiros.mg.gov.br/IT_02.pdf"
        digest = sync.sha256_bytes(b"%PDF-1.7\n")
        record = {"url": old_url, "titulo": "IT 02", "numero_it": "02", "sha256": digest,
            "arquivo": "pdf/historico.pdf", "data_coleta": OLD_DATE}
        self.manifest["documentos"].append(record)
        sync.salvar_json(self.out / "data" / "normas_manifest.json", self.manifest)
        (self.out / "pdf").mkdir()
        (self.out / "pdf/historico.pdf").write_bytes(b"%PDF-1.7\n")
        config = {"versao": 1, "documentos": [{"url": old_url, "sha256_esperado": digest,
            "evidencia": {"data_verificacao": OLD_DATE, "http_status": 200, "url_final": old_url,
                "sha256_obtido": digest}}]}
        sync.salvar_json(self.historicos, config)
        return old_url, config

    def test_registered_historical_is_recollected_and_allows_complete_promotion(self):
        old_url, _ = self.register_historical()
        code, status = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue(status["ok"])
        self.assertEqual(status["contagens"]["links_detectados"], 1)
        self.assertEqual(status["contagens"]["candidatos_totais"], 2)
        self.assertEqual(status["contagens"]["historicos_recoletados"], 1)
        self.assertEqual(status["contagens"]["documentos_anteriores_ausentes"], 0)
        current = json.loads((self.out / "data/normas_manifest.json").read_text())
        doc = next(d for d in current["documentos"] if d["url"] == old_url)
        self.assertEqual(doc["escopo_coleta"], "historico_reconciliado")
        self.assertEqual(doc["sha256"], doc["sha256_esperado"])
        self.assertEqual(doc["situacao"], "nao_verificada")
        self.assertIsNone(doc["url_listada"])
        self.assertNotEqual(doc["data_coleta"], OLD_DATE)
        self.assertTrue(current["metadata"]["coleta_completa"])

    def test_changed_historical_hash_blocks_only_that_document_and_preserves_old_bytes(self):
        old_url, _ = self.register_historical()
        code, status = self.run_main(pdf=b"%PDF-1.7\nconteudo alterado")
        self.assertEqual(code, 4)
        self.assertFalse(status["ok"])
        self.assertEqual(status["contagens"]["historicos_recoletados"], 0)
        self.assertIn("SHA-256 histórico divergente", status["erros"][0]["erro"])
        self.assertEqual((self.out / "pdf/historico.pdf").read_bytes(), b"%PDF-1.7\n")
        self.assertEqual(list((self.out / "pdf").glob("it-02-*.pdf")), [])
        current = json.loads((self.out / "data/normas_manifest.json").read_text())
        doc = next(d for d in current["documentos"] if d["url"] == old_url)
        self.assertEqual(doc["coleta_estado"], "preservado_sem_nova_coleta")
        self.assertEqual(current["metadata"]["data_coleta"], OLD_DATE)

    def test_historical_back_in_index_is_not_duplicated_and_remains_hash_locked(self):
        old_url, _ = self.register_historical()
        html = HTML + f'<a href="{old_url.replace("://", "://www.")}">IT 02</a>'
        code, status = self.run_main(html=html)
        self.assertEqual(code, 0)
        self.assertEqual(status["contagens"]["pdfs"], 2)
        self.assertEqual(status["contagens"]["historicos_fora_indice"], 0)
        code, status = self.run_main(html=html, pdf=b"%PDF-alterado")
        self.assertEqual(code, 4)
        self.assertIn("SHA-256 histórico divergente", status["erros"][0]["erro"])

    def test_reconciled_historical_does_not_hide_another_missing_document(self):
        self.register_historical()
        self.manifest["documentos"].append({"url": "https://bombeiros.mg.gov.br/IT_03.pdf", "titulo": "IT 03"})
        sync.salvar_json(self.out / "data/normas_manifest.json", self.manifest)
        code, status = self.run_main()
        self.assertEqual(code, 4)
        self.assertEqual(status["contagens"]["historicos_recoletados"], 1)
        self.assertEqual(status["contagens"]["documentos_anteriores_ausentes"], 1)

    def test_registered_historical_cannot_replace_empty_index(self):
        self.register_historical()
        with patch.object(sync, "incluir_historicos") as include:
            code, status = self.run_main(html="<html>sem índice</html>")
        self.assertEqual(code, 2)
        self.assertFalse(status["ok"])
        include.assert_not_called()

    def test_invalid_or_missing_registry_blocks_promotion(self):
        _, config = self.register_historical()
        original = json.dumps(config)
        for variation in ("external", "duplicate", "hash", "evidence", "missing"):
            with self.subTest(variation=variation):
                candidate = json.loads(original)
                if variation == "external":
                    candidate["documentos"][0]["url"] = "https://example.com/a.pdf"
                elif variation == "duplicate":
                    candidate["documentos"].append(candidate["documentos"][0])
                elif variation == "hash":
                    candidate["documentos"][0]["sha256_esperado"] = "a" * 64
                elif variation == "evidence":
                    candidate["documentos"][0]["evidencia"]["http_status"] = 404
                sync.salvar_json(self.historicos, candidate)
                if variation == "missing":
                    self.historicos.unlink()
                before = (self.out / "data/normas_manifest.json").read_bytes()
                code, status = self.run_main()
                self.assertEqual(code, 5)
                self.assertFalse(status["ok"])
                self.assertEqual(status["fase"], "reconciliacao_historicos")
                self.assertEqual((self.out / "data/normas_manifest.json").read_bytes(), before)

    def test_partial_base_with_zero_download_errors_is_not_a_previous_complete_success(self):
        self.manifest["metadata"]["coleta_completa"] = False
        sync.salvar_json(self.out / "data/normas_manifest.json", self.manifest)
        code, status = self.run_main(html="<html>sem índice</html>")
        self.assertEqual(code, 2)
        self.assertIsNone(status["ultima_coleta_bem_sucedida"])

    def test_invalid_pdf_preserves_all_published_data_and_timestamp(self):
        before = {p: p.read_bytes() for p in self.out.rglob("*.json")}
        code, status = self.run_main(pdf=b"<html>erro</html>")
        self.assertNotEqual(code, 0)
        self.assertFalse(status["ok"])
        self.assertEqual(status["data_coleta_base"], OLD_DATE)
        self.assertEqual(status["ultima_coleta_bem_sucedida"], OLD_DATE)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
        self.assertFalse((self.out / "pdf").exists())

    def test_missing_previous_document_is_preserved_during_partial_merge(self):
        old_url = "https://bombeiros.mg.gov.br/IT_02.pdf"
        self.manifest["documentos"].append({"url": old_url, "titulo": "IT 02", "numero_it": "02", "texto_path": "texto/it-02.txt"})
        path = self.out / "data" / "normas_manifest.json"
        sync.salvar_json(path, self.manifest)
        sync.salvar_json(self.out / "normas_com_texto.json", {"normas": [{"url": old_url, "texto": "Texto anterior que não pode desaparecer."}]})
        code, status = self.run_main()
        self.assertEqual(code, 4)
        current = json.loads(path.read_text())
        self.assertEqual(current["metadata"]["data_coleta"], OLD_DATE)
        self.assertFalse(current["metadata"]["coleta_completa"])
        self.assertEqual(len(current["documentos"]), 2)
        old_document = next(doc for doc in current["documentos"] if doc["url"] == old_url)
        new_document = next(doc for doc in current["documentos"] if doc["url"] == PDF_URL)
        self.assertEqual(old_document["data_coleta"], OLD_DATE)
        self.assertEqual(old_document["coleta_estado"], "preservado_sem_nova_coleta")
        self.assertNotEqual(new_document["data_coleta"], OLD_DATE)
        corpus = json.loads((self.out / "normas_com_texto.json").read_text())
        self.assertEqual(next(doc for doc in corpus["normas"] if doc["url"] == old_url)["texto"], "Texto anterior que não pode desaparecer.")
        self.assertTrue(status["promocao_parcial"])
        self.assertFalse(status["ok"])
        self.assertEqual(status["contagens"]["documentos_anteriores_ausentes"], 1)

    def test_success_promotes_and_normalizes_www_identity(self):
        self.manifest["documentos"][0]["url"] = PDF_URL.replace("://", "://www.")
        sync.salvar_json(self.out / "data" / "normas_manifest.json", self.manifest)
        code, status = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue(status["ok"])
        self.assertEqual(status["status"], "ok")
        current = json.loads((self.out / "data" / "normas_manifest.json").read_text())
        self.assertEqual(len(current["documentos"]), 1)
        self.assertEqual(current["documentos"][0]["situacao"], "nao_verificada")
        self.assertEqual(status["ultima_coleta_bem_sucedida"], current["metadata"]["data_coleta"])
        self.assertNotEqual(status["ultima_coleta_bem_sucedida"], OLD_DATE)

    def test_failed_extraction_asset_is_not_copied_during_partial_promotion(self):
        html = HTML + '<p><a href="/IT_02.pdf">IT 02</a></p>'
        def extract(path):
            if path.name.startswith("it-02-"):
                return "[ERRO DE EXTRAÇÃO: corrompido]", None
            return "Texto da IT 01", 1
        with patch.object(sync, "extract_pdf_text", side_effect=extract):
            code, status = self.run_main(html=html, extra_args=("--extract-text",))
        self.assertEqual(code, 4)
        self.assertTrue(status["promocao_parcial"])
        self.assertEqual(len(list((self.out / "pdf").glob("it-01-*.pdf"))), 1)
        self.assertEqual(list((self.out / "pdf").glob("it-02-*.pdf")), [])

    def test_empty_compatibility_flag_never_promotes_an_empty_base(self):
        before = (self.out / "data" / "normas_manifest.json").read_bytes()
        code, status = self.run_main(html="<html>nenhum documento</html>", extra_args=("--no-fail-if-empty",))
        self.assertNotEqual(code, 0)
        self.assertFalse(status["ok"])
        self.assertEqual((self.out / "data" / "normas_manifest.json").read_bytes(), before)

    def test_all_sources_timeout_still_reports_current_failure(self):
        session = Mock()
        session.get.side_effect = requests.Timeout("fonte indisponível")
        with patch.object(sync, "get_session", return_value=session), patch.object(sync.time, "sleep"), patch.object(sys, "argv", [str(SCRIPT), "--out", str(self.out)]), contextlib.redirect_stdout(io.StringIO()):
            code = sync.main()
        status = json.loads((self.out / "data" / "sync_status.json").read_text())
        self.assertNotEqual(code, 0)
        self.assertEqual(status["status"], "falha")
        self.assertEqual(len(status["diagnostico"]["tentativas"]), 2)
        self.assertEqual(status["data_coleta_base"], OLD_DATE)
        self.assertIsNotNone(sync.dt.datetime.fromisoformat(status["ultima_tentativa"]).utcoffset())
        self.assertEqual(status["fase"], "acesso_indice")
        self.assertIn("antes da extração", status["motivo"])


if __name__ == "__main__":
    unittest.main()

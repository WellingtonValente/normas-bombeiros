import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("gpt_api", Path(__file__).parents[1] / "scripts/build_gpt_api.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class ApiTests(unittest.TestCase):
    def test_legacy_current_label_is_not_legal_evidence(self):
        self.assertEqual(api.state({"situacao": "vigente/listada", "titulo": "IT 01"})[0], "nao_verificada")
        self.assertEqual(api.state({"url": "https://bombeiros.mg.gov.br/legislacaoantiga/a.pdf"})[0], "historico")
        self.assertEqual(api.state({"titulo": "Minuta da IT 30"})[0], "proposta")
        self.assertEqual(api.state({"titulo": "IT 01 não revogada"})[0], "nao_verificada")
        self.assertEqual(api.state({"titulo": "IT 01 parcialmente revogada"})[0], "nao_verificada")
        self.assertEqual(api.state({"titulo": "Minuta da IT 01 (substitui IT revogada)"})[0], "proposta")

    def test_large_unicode_text_roundtrip_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            text = "--- PÁGINA 1 ---\n" + "Ação técnica. 🔥 " * 2200 + "\n--- PÁGINA 2 ---\nFIM"
            d = {"titulo": "IT 01 - Teste", "numero_it": "99", "texto": text,
                 "url": "https://bombeiros.mg.gov.br/IT_01.pdf", "sha256": "a" * 64}
            for filename, value in [("normas_manifest.json", {"metadata": {"data_coleta": "2025-01-01"}, "documentos": [d]}),
                                    ("normas_com_texto.json", {"normas": [d]})]:
                (root / "data" / filename).write_text(json.dumps(value), encoding="utf-8")
            result = api.build(root)
            self.assertLessEqual(max(map(len, result.values())), api.MAX_RESPONSE_BYTES)
            catalog = json.loads(result["its/01/1.json"])
            ident = catalog["items"][0]["id"]
            count = catalog["items"][0]["total_trechos"]
            recovered = "".join(json.loads(result[f"documentos/{ident}/trechos/{n}.json"])["texto"] for n in range(1, count+1))
            self.assertEqual(recovered, text)
            self.assertEqual(json.loads(result["status.json"])["data_coleta"], "2025-01-01")
            self.assertEqual(json.loads(result["status.json"])["resultado_coleta"], "sem_verificacao_recente")

    def test_old_collection_errors_are_distinct_from_current_index_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            d = {'titulo': 'IT 01', 'url': 'https://bombeiros.mg.gov.br/IT_01.pdf', 'texto': 'texto anterior'}
            data = {
                'normas_manifest.json': {'metadata': {'data_coleta': '2026-05-04', 'total_erros': 33}, 'documentos': [d]},
                'normas_com_texto.json': {'normas': [d]},
                'sync_status.json': {'ok': False, 'status': 'falha', 'fase': 'acesso_indice',
                    'motivo': 'Falha de conexão antes da extração.', 'contagens': {'links_detectados': 0},
                    'diagnostico': {'tentativas': [{'erro': 'timeout'}, {'erro': 'timeout'}]}},
            }
            for name, value in data.items():
                (root / 'data' / name).write_text(json.dumps(value), encoding='utf-8')
            result = json.loads(api.build(root)['status.json'])
            self.assertEqual(result['erros_coleta_base'], 33)
            self.assertEqual(result['erros_acesso_indice_ultima_tentativa'], 2)
            self.assertIsNone(result['erros_documentos_ultima_tentativa'])
            self.assertEqual(result['data_coleta'], '2026-05-04')
            self.assertEqual(result['atualidade_normativa'], 'nao_garantida')
            self.assertFalse(result['coleta_ok'])

    def test_page_numbers_are_pdf_pages_and_split_is_lossless(self):
        text = "--- PÁGINA 3 ---\n" + "á" * 6500 + "\n--- PÁGINA 4 ---\nz"
        parts = list(api.text_parts(text))
        self.assertEqual("".join(p[0] for p in parts), text)
        self.assertEqual(parts[0][1], [3])
        self.assertEqual(parts[1][1], [3, 4])

    def test_reconciled_history_is_explicit_without_certifying_legal_currency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            date = '2026-09-15T05:12:31+00:00'
            d = {'titulo': 'IT 01', 'url': 'https://bombeiros.mg.gov.br/images/IT_01.pdf',
                 'texto': 'texto histórico', 'escopo_coleta': 'historico_reconciliado',
                 'reconciliacao_historica': {'data_verificacao': date, 'sha256_obtido': 'a' * 64}}
            data = {
                'normas_manifest.json': {'metadata': {'data_coleta': date, 'coleta_completa': True,
                    'total_erros': 0, 'total_historicos_reconciliados': 1}, 'documentos': [d]},
                'normas_com_texto.json': {'normas': [d]},
                'sync_status.json': {'ok': True, 'status': 'ok', 'promocao_parcial': False,
                    'contagens': {'erros': 0, 'historicos_recoletados': 1, 'documentos_anteriores_ausentes': 0}},
            }
            for name, value in data.items():
                (root / 'data' / name).write_text(json.dumps(value), encoding='utf-8')
            responses = api.build(root)
            status = json.loads(responses['status.json'])
            self.assertTrue(status['coleta_ok'])
            self.assertTrue(status['base_coleta_completa'])
            self.assertEqual(status['atualidade_normativa'], 'nao_garantida')
            self.assertEqual(status['historicos_reconciliados'], 1)
            self.assertEqual(status['historicos_recoletados_ultima_tentativa'], 1)
            self.assertEqual(status['documentos_anteriores_ausentes'], 0)
            item = json.loads(responses['its/01/1.json'])['items'][0]
            self.assertEqual(item['situacao'], 'historico')
            self.assertEqual(item['reconciliacao_historica'], d['reconciliacao_historica'])
            self.assertEqual(api.state({**d, 'titulo': 'Minuta da IT 01'})[0], 'proposta')

    def test_empty_input_does_not_replace_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                api.build(root)
            self.assertFalse((root / "api").exists())


if __name__ == "__main__":
    unittest.main()

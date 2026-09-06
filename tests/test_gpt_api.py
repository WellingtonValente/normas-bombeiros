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

    def test_page_numbers_are_pdf_pages_and_split_is_lossless(self):
        text = "--- PÁGINA 3 ---\n" + "á" * 6500 + "\n--- PÁGINA 4 ---\nz"
        parts = list(api.text_parts(text))
        self.assertEqual("".join(p[0] for p in parts), text)
        self.assertEqual(parts[0][1], [3])
        self.assertEqual(parts[1][1], [3, 4])

    def test_empty_input_does_not_replace_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                api.build(root)
            self.assertFalse((root / "api").exists())


if __name__ == "__main__":
    unittest.main()

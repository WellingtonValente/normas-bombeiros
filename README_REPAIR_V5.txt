Reparo v5 - OpenAPI + validação de JSONs do GitHub Pages

Arquivos:
- openapi_cbmmg_integrada_v2.yaml: schema corrigido com components/properties.
- scripts/validar_json_pages.py: valida e regrava JSONs publicados em docs/.

Como aplicar:
1) Copie o conteúdo deste pacote para a raiz do repo normas-bombeiros.
2) Rode: .\.venv\Scripts\python.exe scripts\validar_json_pages.py
3) Rode: git add -A && git commit -m "Corrige OpenAPI e valida JSONs do GitHub Pages" && git push origin main

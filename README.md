# CBMMG Rebuild Kit - Normas, JSON e Custom GPT

Este pacote reconstrói a base do **Guia de Prevenção a Incêndios MG** usando a página oficial de Legislação e Normas Técnicas do CBMMG como fonte primária.

## O que este kit entrega

- Script Python para baixar PDFs oficiais do CBMMG.
- Manifesto auditável com URL oficial, categoria, SHA-256, tamanho e data de coleta.
- Extração de texto dos PDFs das Instruções Técnicas.
- JSONs estáticos para GitHub Pages e Custom GPT Actions.
- Cópias de compatibilidade na raiz de `/docs` para preservar o endpoint antigo `normas_com_texto.json`.
- OpenAPI 3.1 revisado.
- Workflow do GitHub Actions para atualização automática semanal.
- Instruções atualizadas para o GPT.
- Política de privacidade base.
- Catálogo inicial de templates profissionais.

## Estrutura recomendada do repositório

```text
normas-bombeiros/
├─ .github/workflows/update_cbmmg_normas.yml
├─ docs/
│  ├─ normas_com_texto.json         # endpoint legado compatível
│  ├─ normas_manifest.json          # endpoint legado compatível
│  ├─ instrucoes_tecnicas_manifest.json
│  ├─ data/
│  │  ├─ normas_manifest.json
│  │  ├─ instrucoes_tecnicas_manifest.json
│  │  ├─ normas_com_texto.json
│  │  ├─ normas_chunks.jsonl
│  │  ├─ links_nao_pdf.json
│  │  └─ erros_download.json
│  ├─ pdf/
│  ├─ texto/
│  └─ templates/formularios/modelos_laudos.json
├─ scripts/sincronizar_normas_cbmmg.py
├─ requirements.txt
├─ openapi_cbmmg_integrada_v2.yaml
├─ gpt_instrucoes_atualizadas.md
└─ privacy-policy.md
```

## Configuração no GitHub

1. Crie ou restaure o repositório `normas-bombeiros`.
2. Suba os arquivos deste kit.
3. Confira se a política de privacidade também existe em `docs/privacy-policy.md` e `docs/privacy-policy.html`, pois somente a pasta `/docs` será publicada no GitHub Pages.
4. Em **Settings > Pages**, selecione:
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/docs`
5. Rode o workflow manualmente em **Actions > Atualizar normas CBMMG > Run workflow**.
6. Aguarde a criação dos JSONs e PDFs em `docs/`.
7. No construtor do Custom GPT, substitua o schema antigo pelo arquivo `openapi_cbmmg_integrada_v2.yaml`.
8. Substitua as instruções antigas pelo conteúdo de `gpt_instrucoes_atualizadas.md`.

## Rodando localmente

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/sincronizar_normas_cbmmg.py --out docs --extract-text
```

## Boas práticas de compliance

- Mantenha sempre o link oficial do CBMMG no manifesto.
- Use SHA-256 para comparar versões.
- Não hospede texto integral de normas ABNT/NBR.
- Não prometa que o GPT substitui RT, laudo, PSCIP, FAT, ART ou aprovação do CBMMG.
- Para templates, trate tudo como minuta técnica a ser revisada por profissional habilitado.

## Atualização do GPT

O GPT deve consultar primeiro:

1. `listarInstrucoesTecnicasCBMMG`, para saber a versão vigente.
2. `listarNormasComTexto`, para responder itens e procedimentos.
3. `listarTemplatesProfissionais`, quando o usuário profissional pedir modelos.

Se o manifesto indicar uma versão diferente de um arquivo antigo do repositório, prevalece o manifesto atual e a página oficial.

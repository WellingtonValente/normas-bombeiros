# CBMMG Rebuild Kit - Normas, JSON e Custom GPT

## Integração revisada em 06/09/2026

A configuração mantida passa a ser `gpt/instructions.md`, `gpt/metadata.json` e
`gpt/openapi.yaml` (API 3.0). Os arquivos de configuração anteriores permanecem
como histórico; não devem ser importados por engano no editor.

O GPT consulta `/api/v1/status.json` e `/api/v1/catalogo.json`, escolhe uma IT ou
categoria e lê apenas o índice e os trechos de uma versão. Cada resposta tem
limite validado de 24.000 bytes. Não há filtro dinâmico por query string no
GitHub Pages: a seleção é feita por caminhos e paginação explícita.

O workflow executa diariamente às 06:37 UTC (03:37 em Brasília), além de execução
manual e mudanças no código. O GitHub pode atrasar execuções agendadas. Testes
e validação precedem a publicação via artefato Pages. Falhas da origem são
registradas em `docs/data/sync_status.json`; um diagnóstico de falha nunca é
apresentado como coleta completa atualizada. Confira os jobs antes de afirmar
que o agendamento e o deploy estão operacionais.

O GitHub versiona a base técnica e a configuração do assistente. Esta API é
somente leitura e não armazena conversas, plantas nem dados pessoais de clientes.
Para continuidade de um caso, o GPT pode gerar um resumo JSON que o próprio
usuário guarda e reanexa na conversa seguinte.

### Validação local

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/build_gpt_api.py --out docs
python scripts/validar_json_pages.py
```

O título, a descrição, a capacidade de pesquisa e as instruções no editor do
GPT não se atualizam sozinhos quando um arquivo GitHub muda. A base consultada
pelas Actions acompanha os endpoints publicados; alterações de configuração
precisam ser aplicadas e testadas no editor.

### Situação normativa e data de referência

Disponibilidade, edição e data de coleta não comprovam vigência. A classificação
legada `vigente/listada` não é propagada pela API nova. Conteúdo histórico e
minutas são sinalizados; requisitos atuais devem ser confrontados com os atos,
emendas, erratas e regras de transição oficiais. As fontes prioritárias ficam
em `config/fontes.json`. Ambientes de homologação não comprovam atualização do
portal de produção.

O acervo herdado em 06/09/2026 registra coleta de 04/05/2026, com 458 documentos
e 33 erros no relatório antigo. A nova estrutura não altera essa data para
simular atualização. A disponibilidade das fontes externas permanece uma
dependência verificável em cada execução.

## Documentação do kit anterior (referência histórica)

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

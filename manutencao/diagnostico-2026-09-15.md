# Diagnóstico da coleta CBMMG de 14/09/2026

Referência inicial: commit `96d52df01c47322524277bf77362cc8754df9d2f`.

## Evidências

- A [execução 34848180675](https://github.com/WellingtonValente/normas-bombeiros/actions/runs/34848180675), em runner Ubuntu na região Azure eastus, registrou `ConnectTimeoutError` nos dois hosts oficiais, com limite de conexão de 10 segundos. O parser não recebeu HTML. O diagnóstico genérico de ausência de links confundia falha de acesso com falha de extração.
- Os jobs de construção e publicação terminaram, mas o job final informou a falha da coleta. Isso preservou corretamente o acervo e tornou pública a indisponibilidade. Esse controle permanece.
- O manifesto anterior tinha 458 documentos, data de coleta de 04/05/2026 e 33 erros. Todos os 33 erros continham entidades HTML literais no endereço. O fallback por regex no HTML bruto criava esses candidatos adicionais, embora BeautifulSoup já tivesse extraído seus endereços decodificados.
- Em 15/09/2026, o índice oficial foi consultado pela web, carregado no navegador e obtido por HTTP com validação TLS ativa. Uma requisição nesta sessão demorou 17,74 segundos. Esse resultado demonstra que 10 segundos podem ser insuficientes nesta rota; isoladamente, não prova a causa de rede do runner GitHub nem permite afirmar bloqueio geográfico, firewall ou proteção antibot.
- O HTML HTTP tinha 1.069.273 caracteres. A versão anterior extraiu 539 candidatos, incluindo 33 com entidades literais. A versão corrigida extraiu 497, sem esses candidatos espúrios e sem duplicatas equivalentes entre hosts/codificações. Os 33 endereços antigos, devidamente decodificados e normalizados, têm correspondência no índice obtido.
- Não foi observada migração da URL nem necessidade de JavaScript para obter os links: são âncoras HTML no índice. Não se utilizou homologação, espelho de terceiros nem índice de busca como conteúdo do acervo.

## Conteúdo novo identificado na fonte primária

A [página oficial](https://www.bombeiros.mg.gov.br/normastecnicas) lista as
[Portarias 83](https://www.bombeiros.mg.gov.br/storage/files/shares/portarias/Portaria_83.pdf)
e [84](https://www.bombeiros.mg.gov.br/storage/files/shares/portarias/Portaria_84.pdf),
de 2026, com alterações envolvendo as ITs 01, 03, 06, 23 e 30.
O artigo 7º da Portaria 84 prevê entrada em vigor 60 dias após a publicação.
Sua presença no índice não autoriza tratar todas as exigências como imediatamente
vigentes; data de publicação e regras de transição precisam de conferência específica.

## Correção e verificação

- Parser HTML como único extrator; entidades decodificadas uma vez e URLs equivalentes deduplicadas.
- Limites de 60 segundos para conexão e 90 para leitura; tentativas limitadas, sem desabilitar TLS.
- Registro de categoria do erro, duração e histórico das tentativas, URL final e SHA-256 do HTML bruto arquivado.
- Preservação da URL listada e da anotação adjacente do índice, sem inferir vigência a partir delas.
- Status da API distingue os erros herdados, as falhas de acesso ao índice e os erros de documentos desta tentativa.
- Coleta vazia nunca retorna sucesso. Preservados os controles de assinatura PDF, extração, SHA-256, origem de produção, promoção parcial explícita e conservação de documentos ausentes.
- 39 testes de regressão passaram antes da aplicação, incluindo reprodução das entidades HTML, falhas de transporte, PDFs inválidos, preservação do acervo e divergências entre status e resultado do processo.

O resultado da coleta posterior deve ser conferido no `docs/data/sync_status.json`
e na execução GitHub correspondente. Este diagnóstico, por si só, não declara
atualização integral nem certificação de vigência normativa.

## Resultado observado após a correção

O código foi aplicado em `main` pelo commit
[`5ce94f6`](https://github.com/WellingtonValente/normas-bombeiros/commit/5ce94f6498a954da3f0b51f63bb01cb91a80d54f).
A [execução 34930795910](https://github.com/WellingtonValente/normas-bombeiros/actions/runs/34930795910)
começou a coleta em 15/09/2026 às 04:57:32 UTC e concluiu às 05:00:07 UTC.
Os dois hosts oficiais responderam HTTP 200 na primeira tentativa, em 4,500 e
4,135 segundos. Como esses tempos ficaram abaixo de 10 segundos, a recuperação
não demonstra que o limite antigo era a única causa: o timeout de 14/09 é
comprovado, mas uma indisponibilidade intermitente de origem ou rota também é
compatível com as evidências. Não foi comprovado bloqueio por IP ou geografia.

| Verificação | Resultado |
|---|---:|
| Links distintos no índice | 497 |
| PDFs baixados e processados | 462 |
| Links não PDF | 35 |
| Erros de download | 0 |
| Documentos novos em relação ao acervo anterior | 12 |
| Documentos antigos ausentes do índice e preservados | 8 |
| Documentos no catálogo publicado | 470 |
| Testes aprovados no runner GitHub | 39 |
| Respostas JSON geradas | 3.541 |
| Maior resposta JSON | 8.762 bytes (limite: 24.000) |

A construção e a publicação terminaram com sucesso. O job de resultado ficou
em falha porque o sincronizador retornou **código 4: coleta parcial**. Isso é
intencional: os oito documentos históricos abaixo continuam preservados, sem
nova coleta nem confirmação de revogação. Os arquivos em `/images/stories/dat/it/`
não aparecem como âncoras do índice consultado:

- `it_01_8edicao_errata_01_2018_portaria_32_2018.pdf`
- `it_01_revisada_pelas_portarias_12_e_17.pdf`
- `it_08_2_edicao_errata_portaria_n_30_2017.pdf`
- `it_08_2a_edicao.pdf`
- `it_12_2a_edicao.pdf`
- `it_22_armazenamento_de_liquidos_inflamaveis_e_combustiveis.pdf`
- `it%20036.pdf`
- `anexo%20a%20-%20it39_blocos%20de%20carnaval.pdf`

O [status público](https://wellingtonvalente.github.io/normas-bombeiros/api/v1/status.json)
foi consultado por HTTP após a publicação e confirmou:

- `sha256_base`: `12366918a044d22cd5a6f5b10bac5a4b569fe7cd1a48627ae5559052ded9b53a`;
- `ultima_coleta_parcial`: `2026-09-15T05:00:06+00:00`;
- `erros_coleta_base`, `erros_acesso_indice_ultima_tentativa` e `erros_documentos_ultima_tentativa`: **0**;
- `promocao_parcial`: **true**, `base_coleta_completa`: **false**;
- data global anterior preservada: `2026-05-04T20:36:47+00:00`;
- `atualidade_normativa`: **nao_garantida**, por não equivaler à certificação jurídica de vigência.

Os 462 documentos recoletados possuem data individual de 15/09/2026. A data
global antiga e o sinal de falha parcial não significam que esses documentos
continuam congelados em maio. Os oito históricos devem ser reconciliados com
evidência oficial antes de se declarar uma coleta integral.

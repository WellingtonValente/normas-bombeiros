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

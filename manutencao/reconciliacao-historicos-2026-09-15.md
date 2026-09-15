# Reconciliação dos oito históricos — 15/09/2026

Base examinada: commit `5d2071404b44715b80d126183af395b0e41aa0df`.
Os oito registros estavam preservados sem nova coleta porque seus endereços
não apareciam como links no índice oficial. Não havia prova de que os PDFs
tivessem deixado de existir ou de que as normas estivessem revogadas.

## Verificação direta

Entre 05:11:48 e 05:12:31 UTC de 15/09/2026, todos os oito endereços responderam
HTTP 200 no portal oficial de produção do CBMMG, com TLS validado. Os PDFs foram
baixados integralmente, abertos e tiveram texto extraído. **Os oito SHA-256
coincidiram integralmente com o acervo anterior.** Não foi necessário substituir
qualquer PDF por material de terceiros ou aceitar conteúdo sem conferência.

| Registro histórico | Páginas | SHA-256 (prefixo) | Equivalência no índice atual |
|---|---:|---|---|
| IT 01, 8ª edição, errata Portaria 32/2018 | 109 | `1168e4edf2548` | Nenhum PDF com o mesmo hash entre os 462 recoletados |
| IT 01, Portarias 12 e 17 | 65 | `eaa81cf54de8` | IT 01, 5ª edição, Portarias 12 e 17/2014 |
| IT 08, 2ª edição, errata Portaria 30/2017 | 46 | `eecf1cec4e1d` | Nenhum PDF com o mesmo hash entre os 462 recoletados |
| IT 08, arquivo `it_08_2a_edicao.pdf` | 26 | `132cdf20c279` | Nenhum PDF com o mesmo hash entre os 462 recoletados |
| IT 12, 2ª edição | 36 | `6a0c4c23ffd1` | Nenhum PDF com o mesmo hash entre os 462 recoletados |
| IT 22, armazenamento de líquidos | 18 | `8ac77176fb3a` | IT 22, 1ª edição, rotulada como revogada no índice |
| IT 36, proteção contra descargas atmosféricas | 3 | `09dc2ab3f60e` | IT 36, 1ª edição, rotulada como revogada no índice |
| Anexo A da IT 39, blocos de carnaval | 2 | `504643cb2127` | Nenhum PDF com o mesmo hash entre os 462 recoletados |

As URLs completas, hashes integrais, datas, tamanhos e equivalentes estão em
[`config/historicos_cbmmg.json`](../config/historicos_cbmmg.json). As três
equivalências foram determinadas por igualdade de bytes via SHA-256, não por
semelhança do título. As outras cinco linhas não comprovam inexistência de uma
edição sucessora; apenas não têm equivalência de bytes entre os PDFs comparados.

## Correção da cobertura e controles

O coletor continua exigindo um índice oficial acessível e não vazio. Após essa
verificação, incorpora apenas as URLs explicitamente reconciliadas no cadastro,
com hash correspondente ao manifesto anterior e à evidência de download. Os oito
arquivos são baixados de novo em cada execução; uma mudança de bytes exige nova
reconciliação documentada. Não se ignora um erro com base em uma verificação passada.

Falha de acesso, PDF inválido, falha de extração, origem não aprovada ou hash
divergente continuam bloqueando o documento, preservando a cópia anterior e
impedindo a declaração de coleta completa. Outra URL anterior ausente, que não
esteja no cadastro, continua gerando pendência. O cadastro não pode substituir
um índice vazio nem duplica um histórico que volte a aparecer no índice.

A API identifica o escopo histórico e fornece a evidência de reconciliação.
A classificação `historico` designa a origem no acervo preservado; não decide
vigência, revogação ou aplicabilidade a um projeto. Os títulos e URLs originais
são mantidos, preservando os identificadores de consulta. Contagens distinguem
links do índice, históricos suplementares e históricos efetivamente recoletados.

Também foi corrigida a recuperação de `ultima_coleta_bem_sucedida`: uma base
explicitamente parcial com zero erros de download não passa a ser considerada
uma coleta geral anterior bem-sucedida.

O resultado operacional deve ser comprovado pela execução GitHub e pelo status
público após a publicação. A verificação inicial dos oito PDFs, isoladamente,
não declara a conclusão da coleta completa.

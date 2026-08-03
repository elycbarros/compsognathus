# Explicação Didática da Execução da Pipeline

Este documento explica, em linguagem didática, como funciona a execução de uma pipeline de scraping modular baseada em plugins, download adaptativo, validação com Pydantic e exportação estruturada.

## Visão geral

A pipeline começa quando uma URL é enviada pela linha de comando e termina quando os dados extraídos são exportados em formatos como CSV, Parquet ou JSON. Entre esses dois pontos, o sistema passa por camadas bem definidas: despacho de plugin, download, parsing, validação, tratamento de falhas e saída.

## Passo 1: entrada via CLI

O processo começa com um comando como `comps scrape URL`. Bibliotecas como Typer organizam comandos e subcomandos a partir de type hints do Python, enquanto Rich melhora a experiência no terminal com tabelas, cores e feedback visual.

## Passo 2: despacho para o plugin correto

Depois de receber a URL, o sistema identifica o domínio e despacha a tarefa para o plugin correspondente.Esse modelo evita um núcleo monolítico com muitos blocos condicionais e segue a lógica de estratégias isoladas por site.

Exemplo:

- `https://site-a.com/imovel/123` vai para o plugin do Site A.
- `https://site-b.com/listagem/456` vai para o plugin do Site B.
- Um novo domínio exige apenas um novo plugin, sem alterar o core do framework.

## Passo 3: download adaptativo

Com o plugin escolhido, o framework precisa obter o conteúdo da página. Para páginas estáticas, um cliente HTTP como `httpx` é mais eficiente, pois realiza a requisição diretamente sem abrir navegador. Para páginas que dependem de JavaScript para renderizar o conteúdo final, a abordagem correta é usar um navegador headless como Playwright.

A lógica prática é:

- Tentar primeiro a forma mais rápida e barata.
- Trocar para navegador quando o HTML inicial não contém os dados desejados.

## Passo 4: retentativas e resiliência de rede

Se a página falhar por timeout, instabilidade ou limitação temporária, o sistema não precisa desistir imediatamente. Com Tenacity, é possível aplicar retentativas com exponential backoff e jitter, reduzindo contenção e ajudando a lidar com falhas transitórias.

Essa camada de resiliência é importante porque scraping real enfrenta instabilidade de rede, páginas intermitentes e bloqueios ocasionais.

## Passo 5: parsing do conteúdo

Depois que o HTML ou JSON chega ao plugin, começa a etapa de parsing. Nessa fase, o código do plugin localiza os elementos relevantes da página e transforma dados brutos em um formato estruturado.

Por exemplo, um plugin imobiliário pode localizar:

- título do anúncio;
- preço;
- área do imóvel;
- localização;
- quantidade de quartos.

O papel do plugin é conhecer a estrutura daquele site específico e traduzir o conteúdo bruto em campos semânticos úteis.

## Passo 6: validação com Pydantic v2

Depois do parsing, os dados extraídos são enviados para um modelo de validação, como `ScrapedRecord`, definido com Pydantic. Os modelos do Pydantic usam type hints para validar a estrutura dos dados em tempo de execução.

Isso significa que o sistema consegue verificar automaticamente se:

- um campo obrigatório está presente;
- o tipo do valor está correto;
- regras adicionais definidas por validadores estão sendo respeitadas.

Se um campo essencial desaparecer porque o HTML do site mudou, a validação falha de forma explícita. Se o projeto estiver usando strict mode, a validação fica ainda mais rígida e evita coerções automáticas indesejadas.

## Passo 7: tratamento gracioso de erros

Em uma coleta em lote, nem todos os registros precisam falhar juntos. Um bom desenho permite que um item com erro seja registrado na auditoria enquanto os demais continuam sendo processados.

Esse comportamento é importante porque, em projetos reais, mudanças parciais de HTML e inconsistências pontuais são normais. A auditoria ajuda a identificar onde houve quebra sem interromper toda a operação.

## Passo 8: exportação dos dados

Depois que os registros passam pela validação, eles podem ser exportados para formatos estruturados como CSV, Parquet, JSON e JSONL. Essa saída permite usar os dados em análise exploratória, pipelines de BI, bancos de dados ou fluxos de Machine Learning.

## Exemplo completo de execução

Considere o seguinte cenário:

1. O usuário executa `comps scrape https://site-imoveis.com/anuncio/123`.
2. A CLI interpreta o comando e chama a rotina principal.
3. O despachante identifica o domínio `site-imoveis.com` e escolhe o plugin correspondente.
4. O downloader tenta buscar a página com a abordagem mais leve primeiro.
5. Se o conteúdo vier incompleto por depender de JavaScript, o fluxo sobe para Playwright.
6. O plugin extrai campos como preço, metragem e bairro.
7. O Pydantic valida se esses campos têm a estrutura esperada.
8. Se um campo obrigatório faltar, o erro é reportado.
9. Se houver falha transitória na rede, Tenacity tenta novamente com backoff.
10. Ao final, os dados válidos são exportados no formato definido.

## Leitura arquitetural em camadas

A arquitetura pode ser entendida como uma sequência de camadas independentes:

| Camada | Responsabilidade |
|---|---|
| CLI | Receber o comando e iniciar o fluxo. |
| Despachante | Escolher o plugin correto pelo domínio. |
| Downloader | Obter o conteúdo com HTTP direto ou navegador headless. |
| Plugin | Conhecer a estrutura do site e extrair os dados. |
| Validação | Garantir contrato de dados com Pydantic. |
| Resiliência | Retentar falhas transitórias e registrar erros parciais. |
| Exportação | Entregar dados estruturados para consumo posterior. |

## Por que essa infra é boa

Esse tipo de infraestrutura é forte porque separa claramente responsabilidades, reduz acoplamento e facilita manutenção. Também melhora testabilidade, já que plugins podem ser testados isoladamente e a validação de dados atua como um contrato formal entre scraping e consumo posterior.

Na prática, isso transforma scraping em engenharia de dados confiável. Em vez de apenas “raspar HTML”, o sistema passa a controlar qualidade, tolerância a falhas e previsibilidade operacional.

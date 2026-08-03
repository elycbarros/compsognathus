# Compsognathus 🦕

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/elycbarros/compsognathus/actions/workflows/tests.yml/badge.svg)](https://github.com/elycbarros/compsognathus/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Compsognathus é um framework de web scraping orientado a plugins. Ele deixa o
trabalho repetitivo — baixar páginas, tentar novamente, identificar o parser,
validar os dados e exportar o resultado — a cargo da CLI, para que cada plugin
se concentre apenas em extrair os dados do seu domínio.

O projeto foi pensado para ser fácil de aprender e suficientemente estruturado
para uso real: exemplos mínimos explicam o contrato do plugin e templates
robustos ajudam a lidar com HTML incompleto e dados variáveis.

![Demonstração da CLI do Compsognathus](docs/assets/cli-demo.svg)

## O que ele oferece

- Plugins registrados por domínio, com despacho automático pela URL.
- Download resiliente com Playwright e fallback HTTP.
- Extração em camadas: dados estruturados, seletores CSS e metatags.
- Exportação para Parquet, CSV, JSON, JSONL e SQLite.
- Diagnóstico de downloads, parsing e campos obrigatórios com `comps validate`.
- Scaffold que cria plugin, fixture e teste em um comando.

Plugins incluídos: ZAP Imóveis, VivaReal, Mercado Livre, Catho e Books to Scrape.

## Validação com dados reais

Além das fixtures sintéticas, a versão 1.3.1 foi validada com uma amostra real
e anonimizada de páginas do ZAP Imóveis e VivaReal:

| Métrica | Resultado |
|---|---:|
| URLs processadas | 8 |
| Downloads concluídos | 8/8 |
| Parses completos | 8/8 |
| Colunas exportadas | 18 |

As URLs e os HTMLs reais não fazem parte do repositório para evitar publicar
dados de terceiros. A suíte automatizada usa equivalentes sintéticos e
determinísticos das estruturas observadas.

## Início rápido

Você precisa de Python 3.11+ e do Chromium usado pelo Playwright.

```bash
git clone https://github.com/elycbarros/compsognathus.git
cd compsognathus

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Crie um arquivo `links.txt` com uma URL HTTP(S) por linha e execute:

```bash
# Confirme os plugins disponíveis antes de baixar qualquer página.
comps scrape links.txt --dry-run

# Raspe e exporte o dataset.
comps scrape links.txt --output dados.parquet

# Inspecione a qualidade da coleta.
comps validate dados.parquet --fail-on-error
comps report dados.parquet --html relatorio.html
```

Para outros formatos e concorrência:

```bash
comps scrape links.txt --format sqlite --output dados.db --concurrency 3
comps scrape links.txt --format jsonl --output dados.jsonl
```

## Como funciona

```text
URLs → downloader → HTML → registry → plugin → ScrapedRecord → dataset
```

O `registry` escolhe o plugin pelo domínio. O plugin retorna um `ScrapedRecord`
com metadados fixos e um dicionário livre de campos; o orquestrador transforma
esses registros em um dataset exportável.

### Decisões técnicas

| Decisão | Motivação | Trade-off |
|---|---|---|
| Plugins por domínio | Isola mudanças frequentes de cada site | Cada domínio precisa de manutenção própria |
| Playwright com fallback HTTP | Combina páginas renderizadas e downloads rápidos | O navegador consome mais recursos |
| Preservar registros com falha | Mantém o dataset auditável e permite reprocessamento | A saída inclui linhas incompletas |
| Fixtures sintéticas | Testes rápidos, seguros e reproduzíveis | Não substituem validações periódicas com páginas reais |

## Criando um plugin

O caminho mais rápido cria código inicial, fixture sintética e teste:

```bash
comps plugins new olx.com.br
```

Depois, adapte os seletores ao HTML real e execute a suíte. Para aprender a
estrutura com calma, use o [template comentado](compsognathus/plugins/example_generic.py)
e o [guia de criação de plugins](docs/writing-a-plugin.md).

Um plugin mínimo segue este contrato:

```python
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


@register("meusite.com.br", schema=["titulo"])
def parse(html: str, url: str) -> ScrapedRecord:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else None
    return ScrapedRecord(url=url, site="meusite", fields={"titulo": titulo})
```

## Qualidade e testes

Use estes comandos antes de enviar alterações:

```bash
ruff check .
pytest -q
pytest --cov=compsognathus --cov-report=term-missing
```

As fixtures em `tests/fixtures/` são sintéticas. Isso mantém os testes rápidos,
reproduzíveis e independentes dos sites externos.

## Estrutura do projeto

```text
compsognathus/
├── core/          # modelo ScrapedRecord e registro de plugins
├── plugins/       # parsers e helpers compartilhados
├── downloader.py  # Playwright, HTTP e tentativas de download
├── scraper.py     # orquestra download, parse e exportação
├── datasets.py    # leitura compartilhada por report e validate
└── cli.py         # comandos da interface

tests/             # testes e fixtures HTML sintéticas
docs/              # documentação aprofundada
```

## Contribuindo

Contribuições são bem-vindas. Mantenha alterações pequenas, inclua testes para
novos comportamentos e execute lint e testes antes de abrir um pull request.
Para novos sites, prefira dados estruturados (JSON-LD ou Next.js) antes de
seletores CSS frágeis.

## Segurança e uso responsável

Respeite os termos de uso, limites de acesso e políticas dos sites coletados.
Não inclua credenciais, cookies, dados pessoais ou páginas reais sensíveis nas
fixtures. Para relatar uma vulnerabilidade, use uma divulgação privada pelo
repositório, sem publicar detalhes exploráveis em uma issue pública.

## Licença

Compsognathus é software de código aberto sob a licença [MIT](LICENSE).

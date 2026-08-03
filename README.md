# Compsognathus 🦕

> **Framework genérico de web scraping por plugins** — extraia dados estruturados de qualquer site com uma CLI simples e arquitetura extensível.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://github.com/elycbarros/compsognathus/actions/workflows/tests.yml/badge.svg)](https://github.com/elycbarros/compsognathus/actions/workflows/tests.yml)

---

## O que é

Compsognathus é um framework de scraping orientado a **plugins**. Você registra um plugin para um domínio (com ~20 linhas de Python) e a CLI cuida do resto: download com Playwright, retry automático, exportação em Parquet/CSV e relatório de qualidade.

**Plugins bundled — 4 domínios/segmentos distintos:**

| Plugin | Site | Campos extraídos |
|---|---|---|
| `zapimoveis` | zapimoveis.com.br | preço, área, quartos, bairro, endereço |
| `vivareal` | vivareal.com.br | preço, área, quartos, bairro, endereço |
| `mercadolivre` | mercadolivre.com.br | produto, preço, avaliação, vendedor, condição |
| `catho` | catho.com.br | cargo, empresa, salário, cidade, regime |
| `books_toscrape` | books.toscrape.com | título, preço, avaliação, disponibilidade, UPC |

---

## Arquitetura

```
URL
 │
 ▼
downloader.py          ← Playwright (headless) + httpx (fallback)
 │                       Delay anti-rate-limit · Retry com backoff exponencial
 ▼
HTML salvo em disco
 │
 ▼
registry.py            ← Detecta o domínio e despacha para o plugin correto
 │
 ▼
plugin/[site].py       ← Extração em camadas: JSON-LD → CSS → meta tags
 │
 ▼
ScrapedRecord          ← Modelo genérico: fields: dict[str, Any]
 │
 ▼
scraper.py             ← Achata fields em colunas do DataFrame
 │
 ▼
dados.parquet / .csv   ← Saída final
```

---

## Setup

```bash
# 1. Clone e entre no diretório
git clone https://github.com/seu-usuario/compsognathus.git
cd compsognathus

# 2. Instale o pacote e as dependências
pip install -e ".[dev]"

# 3. Instale o Chromium para o Playwright
playwright install chromium
```

---

## Uso

### Scraping a partir de arquivo de URLs

```bash
# Crie um arquivo com as URLs (uma por linha)
echo "https://www.zapimoveis.com.br/imovel/..." > links.txt

# Valide as URLs e os plugins disponíveis sem realizar downloads (Dry-Run)
comps scrape links.txt --dry-run

# Raspe e exporte
comps scrape links.txt --output dados.parquet
comps scrape links.txt --output dados.csv --format csv
```

### Scraping de URL única

```bash
comps scrape "https://www.mercadolivre.com.br/p/MLB..." --output produto.parquet
```

### Relatório de qualidade

```bash
comps report dados.parquet
```

Saída:
```
📊 Relatório: dados.parquet

Total de registros    12
Registros completos   11/12 (91%)
Sites coletados       zapimoveis, vivareal
Colunas               10

Estatísticas numéricas:
┌───────────────┬──────────────┬──────────┬──────────────┐
│ Campo         │ Média        │ Mín      │ Máx          │
├───────────────┼──────────────┼──────────┼──────────────┤
│ preco         │ 650,000.00   │ 320,000  │ 1,200,000    │
└───────────────┴──────────────┴──────────┴──────────────┘
```

### Listar plugins disponíveis

```bash
comps plugins list
```

---

## Adicionando um novo plugin

Crie um novo parser em **20 linhas**. Veja o template comentado em [`plugins/example_generic.py`](compsognathus/plugins/example_generic.py) e o tutorial completo em [`docs/writing-a-plugin.md`](docs/writing-a-plugin.md).

```python
# compsognathus/plugins/meusite.py
from bs4 import BeautifulSoup
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

@register("meusite.com.br", schema=["titulo", "preco"])
def parse(html: str, url: str) -> ScrapedRecord:
    soup = BeautifulSoup(html, "html.parser")
    titulo = soup.find("h1").get_text(strip=True)
    return ScrapedRecord(url=url, site="meusite", fields={"titulo": titulo})
```

Depois, adicione o import em `compsognathus/plugins/__init__.py`:
```python
import compsognathus.plugins.meusite  # noqa: F401
```

Pronto. O comando `comps plugins list` já reconhecerá seu plugin.

---

## Testes

```bash
# Executa toda a suíte de testes
pytest tests/ -v

# Com cobertura de código
pytest tests/ --cov=compsognathus --cov-report=term-missing
```

---

## Estrutura do projeto

```
compsognathus/
├── compsognathus/
│   ├── core/
│   │   ├── record.py       # ScrapedRecord — modelo genérico de dados
│   │   └── registry.py     # @register decorator + dispatcher por domínio
│   ├── plugins/
│   │   ├── zapimoveis.py   # Plugin: imóveis (ZAP)
│   │   ├── vivareal.py     # Plugin: imóveis (VivaReal)
│   │   ├── mercadolivre.py # Plugin: e-commerce (Mercado Livre)
│   │   ├── catho.py        # Plugin: vagas (Catho)
│   │   └── example_generic.py  # Template didático para novos plugins
│   ├── downloader.py       # Playwright + httpx com retry e anti-rate-limit
│   ├── scraper.py          # Orquestrador: download → parse → export
│   └── cli.py              # Interface CLI (typer + rich)
├── tests/
│   ├── fixtures/           # HTMLs sintéticos para testes determinísticos
│   ├── test_core.py        # Testes do ScrapedRecord e registry
│   └── test_parsers.py     # Testes de todos os parsers com fixtures
└── docs/
    └── writing-a-plugin.md # Tutorial: crie um parser em 20 linhas
```

---

## Por que "Compsognathus"?

O Compsognathus foi um dos menores dinossauros conhecidos — ágil, eficiente e adaptável. Como este framework: leve o suficiente para rodar com `pip install`, mas poderoso o suficiente para raspar qualquer site.

Inspirado no RAPTOR 🦖, seu primo maior — uma ferramenta interna de scraping imobiliário com stack MLOps completa.

---

## Licença

MIT — veja [LICENSE](LICENSE).

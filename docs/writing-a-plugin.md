# Como criar um Plugin para o Compsognathus

Este guia mostra dois caminhos: um **exemplo mínimo** para entender o contrato
de um plugin e um **template robusto** para adaptar a sites reais. Um parser
mínimo cabe em poucas linhas; um parser confiável normalmente precisa de
tratamento de campos ausentes, conversão de valores e testes.

---

## Estrutura de um Plugin

Todo plugin é um arquivo `.py` com três elementos:

1. **Docstring** — descreve o que o plugin faz
2. **`@register`** — vincula o plugin a um domínio
3. **`parse(html, url)`** — extrai os dados e retorna um `ScrapedRecord`

```python
"""
Plugin: Nome do Site (dominio.com.br)
Extrai: campo1, campo2, campo3
"""
from bs4 import BeautifulSoup
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

@register("dominio.com.br", schema=["campo1", "campo2"])
def parse(html: str, url: str) -> ScrapedRecord:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    campo1 = h1.get_text(strip=True) if h1 else None
    return ScrapedRecord(
        url=url,
        site="meusite",
        fields={"campo1": campo1},
    )
```

---

## Passo a Passo

### 1. Inspecione o site alvo

Abra o site no navegador, vá em **F12 → Elements** e identifique:
- Onde está o dado que você quer? (`<h1>`, `<span class="price">`, etc.)
- O site usa JSON-LD? (`<script type="application/ld+json">`)
- O site usa Next.js? Procure `__NEXT_DATA__` ou `self.__next_f.push`.

> **Dica:** Dados em JSON-LD e payloads do Next.js são mais estáveis que
> seletores CSS, que podem mudar a cada redesign do site.

### 2. Copie o template

```bash
cp compsognathus/plugins/example_generic.py compsognathus/plugins/meusite.py
```

### 3. Edite o arquivo

Substitua:
- `"example.com"` → domínio do seu site
- `schema=[...]` → lista dos campos que você extrai
- A lógica de extração dentro de `parse()`

### 4. Ative o plugin

Adicione o import em `compsognathus/plugins/__init__.py`:

```python
import compsognathus.plugins.meusite  # noqa: F401
```

### 5. Crie uma fixture de teste

Crie `tests/fixtures/meusite_sample.html` com um HTML de exemplo do site
(pode ser uma versão simplificada/sintética).

### 6. Escreva um teste

```python
# tests/test_parsers.py
def test_meusite_extrai_campo1(load_fixture):
    from compsognathus.plugins.meusite import parse
    html = load_fixture("meusite_sample.html")
    rec = parse(html, "https://meusite.com/item/1")
    assert rec.fields["campo1"] is not None
```

### 7. Execute os testes

```bash
pytest tests/ -v
```

---

## Estratégias de Extração

### Estratégia 1: JSON-LD (Schema.org) ✅ Preferencial

Muitos sites incluem dados estruturados em tags `<script type="application/ld+json">`.
Esses dados seguem o padrão Schema.org e são altamente estáveis.

```python
for script in soup.find_all("script", type="application/ld+json"):
    data = json.loads(script.string or "")
    if data.get("@type") == "Product":
        preco = data["offers"]["price"]
```

### Estratégia 2: JSON embutido (Next.js) ✅ Estável

Sites construídos com Next.js podem incluir dados em `__NEXT_DATA__` (modelo
mais antigo) ou em chamadas `self.__next_f.push` (React Flight, modelo atual).
O projeto já oferece `iter_next_payloads()` para lidar com ambos; prefira esse
helper em vez de repetir a lógica de decodificação no plugin.

```python
from compsognathus.plugins._next_data import iter_next_payloads

for payload in iter_next_payloads(soup):
    # Percorra cada payload recursivamente para encontrar os dados.
    pass
```

### Estratégia 3: Seletores CSS 🟡 Funcional (mas frágil)

Use `data-testid` e `data-cy` (atributos de teste) — são mais estáveis que classes CSS.

```python
el = soup.select_one('[data-testid="product-price"]')
preco = el.get_text(strip=True) if el else None
```

Evite seletores por classe gerada (ex: `.sc-bdfxgF.kiHWNp`) — mudam a cada build.

### Estratégia 4: Meta tags 🟢 Boa para título/descrição

```python
meta = soup.find("meta", property="og:title")
titulo = meta.get("content") if meta else None
```

---

## Exemplo Completo: Books to Scrape

```python
"""
Plugin: Books to Scrape (books.toscrape.com)
Site de demonstração open-to-scrape — ideal para testes sem WAF.
Extrai: titulo, preco, avaliacao, disponibilidade
"""
import re
from bs4 import BeautifulSoup
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

@register("books.toscrape.com", schema=["titulo", "preco", "avaliacao"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser para books.toscrape.com — extrai livros com preço e avaliação."""
    soup = BeautifulSoup(html, "html.parser")
    errors = []

    # Título via h1
    titulo = soup.find("h1")
    titulo = titulo.get_text(strip=True) if titulo else None
    if not titulo:
        errors.append("titulo")

    # Preço via seletor CSS estável
    preco_el = soup.select_one("p.price_color")
    preco = None
    if preco_el:
        m = re.search(r"[\d.]+", preco_el.get_text())
        preco = float(m.group(0)) if m else None
    if not preco:
        errors.append("preco")

    # Avaliação (1-5) via classe da tag <p>
    rating_el = soup.select_one("p.star-rating")
    avaliacao = None
    if rating_el:
        classes = rating_el.get("class", [])
        word = next((c for c in classes if c != "star-rating"), None)
        avaliacao = RATING_MAP.get(word)

    return ScrapedRecord(
        url=url,
        site="books_toscrape",
        fields={"titulo": titulo, "preco": preco, "avaliacao": avaliacao},
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
```

---

## Campos e Tipos Recomendados

| Tipo de dado | Campo sugerido | Tipo Python |
|---|---|---|
| Título / Nome | `titulo`, `produto`, `cargo` | `str` |
| Preço numérico | `preco`, `salario` | `float` |
| Avaliação (0-5) | `avaliacao` | `float` |
| Contagem | `quartos`, `num_avaliacoes` | `int` |
| Texto longo | `descricao` | `str` (máx 1000–2000 chars) |
| Localização | `cidade`, `estado`, `bairro` | `str` |
| Data | `data_publicacao` | `str` (ISO 8601) |
| URL | `url_imagem` | `str` |
| Booleano | `disponivel`, `novo` | `bool` |

---

## Dúvidas?

Veja os plugins bundled como referência:
- [`zapimoveis.py`](../compsognathus/plugins/zapimoveis.py) — exemplo com 3 camadas de extração
- [`mercadolivre.py`](../compsognathus/plugins/mercadolivre.py) — exemplo com JSON-LD Schema.org Product
- [`catho.py`](../compsognathus/plugins/catho.py) — exemplo com JSON-LD Schema.org JobPosting
- [`example_generic.py`](../compsognathus/plugins/example_generic.py) — template minimalista comentado

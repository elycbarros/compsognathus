# Como criar um Plugin para o Compsognathus

Este guia ensina como usar a CLI para gerar e testar a estrutura de um plugin. Um parser mínimo requer poucas linhas, mas a internet real é instável: parsers dependem intimamente da estrutura da fonte e exigem manutenção quando o HTML ou o *payload* muda. 

O foco deste guia é garantir que, quando a fonte mudar, seu plugin falhe de forma elegante através do uso de `ScrapedRecord` e de auditoria controlada.

---

## 1. Scaffold Inicial de Código (Automático)

O framework resolve a parte chata de registrar arquivos e suítes de teste automaticamente. Evite criar arquivos à mão e deixe o CLI montar as bases.

Abra seu terminal na raiz do projeto e execute:

```bash
comps plugins new meusite.com.br
```

Este único comando gera:
1. O parser inicial em `compsognathus/plugins/meusite_com_br.py` com o `@register`.
2. Uma string de registro no arquivo `compsognathus/plugins/__init__.py` para garantir que ele seja descoberto.
3. Uma fixture de teste base (HTML vazio) em `tests/fixtures/meusite_com_br_sample.html`.
4. Um arquivo de teste unitário base em `tests/test_meusite_com_br.py`.

---

## 2. Inspecionando o Alvo e Decidindo a Estrutura

Antes de programar o parser, use seu navegador para acessar a URL. Vá ao **Inspetor (F12) → Elements** e procure os dados seguindo essa hierarquia de preferência técnica:

1. **JSON-LD (Schema.org):** Procure pela tag `<script type="application/ld+json">`. Se existir e contiver o dado, use isso. É o método mais imune a quebras cosméticas.
2. **Payloads Embutidos de SPAs (Next.js/Nuxt):** Procure pelas strings `__NEXT_DATA__` ou `self.__next_f.push`. Os dados estarão em JSON formatado dentro do HTML.
3. **Atributos de Teste (`data-testid` / `data-qa` / `aria-label`):** Muitas aplicações possuem âncoras semânticas resistentes a mudanças de estilo.
4. **Seletores Auto-Healing (`AdaptiveSelector`):** Para elementos HTML dinâmicos sujeitos a mudanças de classes CSS (como Tailwind ou styled-components), use `AdaptiveSelector.find_one(...)` ou `AdaptiveSelector.extract_text(...)`. Ele calcula similaridade de nós e recupera o elemento mesmo com classes alteradas.
5. **Seletores CSS Genéricos:** Procure classes estáveis de hierarquia que referenciam o dado (ex: `<div class="price-box">`).

---

## 3. O Contrato de Extração

No arquivo `.py` do seu plugin (`compsognathus/plugins/meusite_com_br.py`), você pode utilizar o `AdaptiveSelector` para uma extração resiliente:

```python
"""
Plugin: Nome do Site (meusite.com.br)
"""
from bs4 import BeautifulSoup
from compsognathus.core.adaptive import AdaptiveSelector
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

@register("meusite.com.br", schema=["titulo", "preco"])
def parse(html: str, url: str) -> ScrapedRecord:
    soup = BeautifulSoup(html, "html.parser")
    errors = []

    # Extração resiliente com AdaptiveSelector
    titulo = AdaptiveSelector.extract_text(
        soup,
        ["h1.product-title", "h1", "div.title"],
        default="",
    )
    if not titulo:
        errors.append("titulo")

    preco = AdaptiveSelector.extract_text(
        soup,
        ["span.price-box", "span.price"],
        text_pattern="R$",
        default="",
    )
    if not preco:
        errors.append("preco")

    return ScrapedRecord(
        url=url,
        site="meusite",
        fields={"titulo": titulo or None, "preco": preco or None},
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
```

O `@register` atua vinculando seu parser a URLs provindas daquele domínio base, e declarando formalmente o esquema de chaves que este parser retornará. Isso é usado na frente para unificar os esquemas no Parquet final.

A lógica de auditoria obriga que você, no parser, identifique quando campos centrais se encontrem ausentes (devido ao layout mudar subitamente) e inclua os nomes dessas chaves dentro da lista `parse_errors`. Isso alimentará os diagnósticos da ferramenta principal.

### Contrato tipado e política de download (opcionais)

Quando os tipos dos dados forem importantes, declare um modelo Pydantic. O
framework preserva os campos extras, mas marca o registro como inválido quando
um tipo ou restrição não for atendido:

```python
from pydantic import BaseModel
from compsognathus.downloader import DownloadPolicy

class Produto(BaseModel):
    titulo: str
    preco: float

@register(
    "meusite.com.br",
    schema=["titulo", "preco"],
    model=Produto,
    download_policy=DownloadPolicy(preferred="stealth_browser", timeout_seconds=20.0),
)
def parse(html: str, url: str) -> ScrapedRecord:
    ...
```

Estratégias de download disponíveis:
- `browser_first`: Tenta Chromium headless via Playwright, fallback para HTTPX.
- `httpx_first`: Tenta HTTPX direto primeiro; ideal para sites estáticos rápidos.
- `stealth_browser`: Ativa evasão profunda de anti-bot no navegador (para portais protegidos por Cloudflare/Kasada).
- `stealth_http`: Requisições HTTP com camuflagem de TLS e headers de navegador modernos.
- `browser_only` / `httpx_only`: Restringe estritamente a um único transporte.

## 4. Plugin externo instalável

Um pacote externo pode registrar plugins sem editar o código do Compsognathus.
Exponha uma função sem argumentos que use `@register` e declare o entry point
no `pyproject.toml` do pacote:

```toml
[project.entry-points."compsognathus.plugins"]
meu_site = "meu_pacote.plugin:register_plugin"
```

```python
from compsognathus.core.registry import register

def register_plugin():
    @register("meusite.com.br", schema=["titulo"])
    def parse(html: str, url: str):
        ...
```

Depois de instalar o pacote, confirme a descoberta com:

```bash
comps plugins list
```

O comando exibe a origem e a versão do plugin. Dois plugins não podem registrar
o mesmo domínio; o conflito é reportado sem substituir silenciosamente o
parser já carregado.

Cada execução também produz um manifesto ao lado do dataset, por exemplo
`dados.run.json`. Ele pode ser usado por ferramentas externas para comparar
duração, retries, cache, status HTTP e falhas sem analisar logs.

---

## 5. Testes do Plugin

Você jamais precisará testar seu plugin rodando ele na internet aberta para confirmar seu parse localmente, evite banimentos acidentais desenvolvendo sempre usando a *fixture* estática que o framework criou pra você.

1. Navegue até o site real.
2. Salve o HTML renderizado real, e preencha a sua *fixture* em `tests/fixtures/meusite_com_br_sample.html`. Reduza o HTML para ter apenas 5 a 10kb preservando o nó pai da estrutura que você raspa.
3. Altere o teste automatizado criado:

```python
# tests/test_meusite_com_br.py
def test_meusite_com_br_extrai_dados(load_fixture):
    from compsognathus.plugins.meusite_com_br import parse
    html = load_fixture("meusite_com_br_sample.html")
    rec = parse(html, "https://meusite.com.br/item/1")
    
    assert rec.fields["titulo"] is not None
    assert rec.parse_ok is True
    assert not rec.parse_errors
```

Rode os testes especificamente do seu plugin:
```bash
pytest tests/test_meusite_com_br.py -v
```

---

## 6. Dúvidas Frequentes

Se o *payload* Next.js (como o de React Flight) for complexo de desembaraçar à mão, o projeto já oferece um helper importável para desempacotar strings de servidor `self.__next_f.push`. 

Acesse e avalie arquivos da própria base do projeto em `compsognathus/plugins/` (como `vivareal` e `mercadolivre`) para usar de exemplo para seus casos mais difíceis, prestando atenção em como os helpers compartilhados de `compsognathus/plugins/` são utilizados.

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
3. **Atributos de Teste (`data-testid`):** Muitas aplicações possuem âncoras para QAs (ex: `data-testid="product-price"`). São resistentes a mudanças de cor e tipografia.
4. **Seletores CSS Genéricos:** O pior cenário, procure Classes CSS de hierarquia que referenciam o dado (ex: `<div class="price-box">`). Jamais selecione classes ofuscadas/criptográficas geradas por build como `.sc-bdfxgF.kiHWNp`, elas mudam na próxima compilação do site alvo.

> **Regra de Ouro:** Não descreva um plugin como “resistente a qualquer mudança de site”. Todo scraper que depende da árvore DOM exige manutenção reativa à evolução da UI/UX daquele site.

---

## 3. O Contrato de Extração

No arquivo `.py` do seu plugin (`compsognathus/plugins/meusite_com_br.py`), você verá uma estrutura similar a esta:

```python
"""
Plugin: Nome do Site (meusite.com.br)
"""
from bs4 import BeautifulSoup
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

@register("meusite.com.br", schema=["titulo", "preco"])
def parse(html: str, url: str) -> ScrapedRecord:
    soup = BeautifulSoup(html, "html.parser")
    errors = []

    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else None
    if not titulo:
        errors.append("titulo")

    return ScrapedRecord(
        url=url,
        site="meusite",
        fields={"titulo": titulo, "preco": None},
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
```

O `@register` atua vinculando seu parser a URLs provindas daquele domínio base, e declarando formalmente o esquema de chaves que este parser retornará. Isso é usado na frente para unificar os esquemas no Parquet final.

A lógica de auditoria obriga que você, no parser, identifique quando campos centrais se encontrem ausentes (devido ao layout mudar subitamente) e inclua os nomes dessas chaves dentro da lista `parse_errors`. Isso alimentará os diagnósticos da ferramenta principal.

---

## 4. Testes do Plugin

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

## 5. Dúvidas Frequentes

Se o *payload* Next.js (como o de React Flight) for complexo de desembaraçar à mão, o projeto já oferece um helper importável para desempacotar strings de servidor `self.__next_f.push`. 

Acesse e avalie arquivos da própria base do projeto em `compsognathus/plugins/` (como `vivareal` e `mercadolivre`) para usar de exemplo para seus casos mais difíceis, prestando atenção de como os helpers importáveis (localizados em `compsognathus/parsers/`) foram utilizados.

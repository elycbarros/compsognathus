# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [Em desenvolvimento]

### Corrigido
- `comps report` agora normaliza valores booleanos textuais antes de calcular a taxa de sucesso, inclusive no relatório HTML.
- A prévia da CLI aceita campos aninhados, como listas e dicionários, sem falhar ao verificar valores ausentes.
- A validação de schema trata `NaN` como campo ausente, preservando a confiabilidade de `parse_ok`.
- `DownloadResult.size_bytes` e os logs de download agora medem o tamanho UTF-8 real, em vez da quantidade de caracteres.

### Documentação
- Documentação inteiramente revisada para centralizar o `README.md` como entrada rápida executiva, transferindo a carga didática integralmente para `DIDATICO.md` e a carga arquitetural profunda para `O_QUE_SOU.md`.
- Esclarecimento na hierarquia do downloader corrigido nos diagramas para afirmar que `Playwright` é a primeira camada, servindo `httpx` como fallback resiliente.
- Métricas e números absolutos convertidos para formato dinâmico, evitando rápida desatualização de indicadores da suíte de testes.

### Melhorado
- CI ampliado com Ruff e matriz de testes do Python 3.11 ao 3.14.
- Leitura de datasets foi centralizada para manter `comps report` e `comps validate` consistentes.
- Registro de plugins passou a usar um contrato nomeado, mais fácil de compreender e tipar.
- Fixtures HTML foram centralizadas em `tests/conftest.py`.

---

## [1.3.1] — 2026-08-03

### Corrigido
- Parsers imobiliários compatíveis com os payloads atuais `self.__next_f.push` do VivaReal e ZAP.

### Adicionado
- Comando `comps validate` para diagnosticar falhas de download, parsing e campos ausentes.

---

## [1.3.0] — 2026-08-03

### Melhorado
- **CLI mais segura**: valida URLs HTTP/HTTPS, infere o formato pela extensão do arquivo e rejeita concorrência inválida.
- **Scaffolding completo**: `comps plugins new` cria o plugin, fixture, teste e registro automático do import.
- **Pipeline auditável**: falhas de download/parsing e metadados de qualidade são preservados no resultado.
- **Extração estruturada**: suporte compartilhado a JSON-LD com `@graph`.

### Testes
- Suíte ampliada cobrindo falhas de rede, schema, CLI, JSON-LD e pipeline.

---

## [1.2.0] — 2026-08-03

### Adicionado
- **Exportação Multi-Formato**: Suporte completo para exportar em JSON, JSONL (`.jsonl` / `.ndjson`) e SQLite (`.db` / `.sqlite`) além de Parquet e CSV.
- **Scaffolding de Plugins (`comps plugins new <dominio>`)**: Comando CLI interativo que gera automaticamente o código do plugin, fixture sintética e testes unitários.
- **Downloads Concorrentes (`--concurrency N` / `-c N`)**: Suporte a downloads simultâneos em paralelo via ThreadPoolExecutor para alta performance em grandes listas de URLs.
- **Relatório HTML Visual (`comps report <arquivo> --html relatorio.html`)**: Exporte relatórios visuais responsivos em página única HTML com métricas e prévia dos dados.
- **Relatórios de Cobertura no CI**: Configurado upload de artefatos XML de cobertura de código no GitHub Actions.
- **Rastreabilidade do pipeline**: URLs com falha de download ou parsing permanecem no dataset final com erro e método de download.
- **Qualidade centralizada**: campos declarados no schema do plugin são validados pelo orquestrador.
- **Scaffolding completo**: `plugins new` também registra o import e cria um teste executável.

---

## [1.1.0] — 2026-08-03

### Adicionado
- **Plugin demo `books.toscrape.com`**: Plugin funcional para o site sandbox didático open-to-scrape (extrai título, preço, avaliação, disponibilidade, UPC e categoria).
- **CLI `--dry-run`**: O comando `comps scrape --dry-run` permite validar a lista de URLs e checar quais plugins compatíveis estão registrados antes de realizar downloads.
- **Suíte de testes estendida**: testes unitários e de integração cobrindo os plugins e opções da CLI.

---

## [1.0.0] — 2026-08-03

### Adicionado
- **Core genérico**: `ScrapedRecord` com `fields: dict[str, Any]` — schema livre por domínio
- **Sistema de plugins**: decorator `@register(domain, schema=[...])` para auto-registro por domínio
- **4 plugins bundled em 3 domínios distintos**:
  - `zapimoveis.py` — imóveis (ZAP Imóveis), extração multi-camadas (`__NEXT_DATA__` → CSS → JSON-LD)
  - `vivareal.py` — imóveis (VivaReal), mesma arquitetura de 3 camadas
  - `mercadolivre.py` — e-commerce, extração via Schema.org `Product`
  - `catho.py` — vagas de emprego, extração via Schema.org `JobPosting`
- **Plugin template** `example_generic.py` — tutorial passo-a-passo comentado para criar novos plugins
- **Downloader resiliente**: Playwright stealth + fallback httpx, retry com backoff exponencial (tenacity), delay anti-rate-limit (1–2s), validação anti-WAF
- **CLI** (`comps` / `compsognathus`):
  - `comps scrape` — pipeline download → parse → export (`.parquet` ou `.csv`)
  - `comps report` — estatísticas e prévia do dataset
  - `comps plugins list` — tabela de plugins registrados com schemas
- **Export**: `.parquet` (padrão, via pandas + pyarrow) e `.csv`
- **Testes**: Suíte de testes offline com fixtures HTML sintéticas.
- **Documentação**: README de portfólio com diagrama de arquitetura + `docs/writing-a-plugin.md`

---

[1.3.1]: https://github.com/elycbarros/compsognathus/releases/tag/v1.3.1
[1.3.0]: https://github.com/elycbarros/compsognathus/releases/tag/v1.3.0
[1.2.0]: https://github.com/elycbarros/compsognathus/releases/tag/v1.2.0
[1.1.0]: https://github.com/elycbarros/compsognathus/releases/tag/v1.1.0
[1.0.0]: https://github.com/elycbarros/compsognathus/releases/tag/v1.0.0

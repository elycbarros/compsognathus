# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

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
- **Testes**: 32 testes com fixtures HTML sintéticas (nenhum acesso à internet necessário)
- **Documentação**: README de portfólio com diagrama de arquitetura + `docs/writing-a-plugin.md`

---

## [Não lançado] — v1.1.0 (próximos passos)

### Planejado
- Plugin `books.toscrape.com` — demo open-to-scrape sem WAF (mostrado no tutorial)
- GitHub Actions badge funcional no README
- `comps scrape --dry-run` — valida URLs e plugins disponíveis sem baixar nada
- `pytest-cov` no workflow CI com relatório de cobertura

---

[1.0.0]: https://github.com/elycbarros/compsognathus/releases/tag/v1.0.0

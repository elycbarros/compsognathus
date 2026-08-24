# Guia Didático de Execução

Este guia fornece um **passo a passo** prático para iniciantes no uso do `compsognathus`. Sem aprofundamento excessivo na teoria de sistemas (que você pode conferir em [`O_QUE_SOU.md`](O_QUE_SOU.md)), vamos abordar todo o ciclo de vida: instalação, uso dos comandos básicos, inspeção dos resultados e tratamento de problemas triviais.

---

## 1. Pré-requisitos

Certifique-se de que o seu ambiente atende aos seguintes requisitos:
- **Python 3.11** ou superior instalado;
- O gerenciador `pip` atualizado;
- Git instalado (para poder clonar o repositório).

---

## 2. Clonagem e Configuração do Ambiente

Abra o seu terminal (Bash, Zsh ou PowerShell) e clone o repositório oficial:

```bash
git clone https://github.com/elycbarros/compsognathus.git
cd compsognathus
```

É considerada uma excelente prática em Python utilizar ambientes virtuais para não "sujar" o seu sistema com dependências de terceiros.

```bash
# Crie o ambiente (a pasta .venv será criada ocultamente)
python -m venv .venv

# Ative o ambiente (Para MacOS / Linux)
source .venv/bin/activate
# Ative o ambiente (Para Windows)
# .venv\Scripts\activate
```

---

## 3. Instalação e Preparação

Instale o framework no modo editável e instale os pacotes de desenvolvimento. Isso permitirá que você adicione plugins depois.

```bash
pip install -e ".[dev]"
```

Em seguida, instale o Chromium se os plugins usados dependerem de JavaScript. Plugins configurados com `httpx_first` ou `httpx_only` não precisam iniciar o navegador.

```bash
playwright install chromium
```

Para confirmar que a aplicação foi instalada globalmente (dentro daquele ambiente virtual), peça a versão:

```bash
comps --help
```

---

## 4. O Comportamento do Downloader

Antes de raspar algo, é crucial entender como a ferramenta trata o acesso ao site para prever eventuais percalços:
1. **Política do plugin**: O domínio escolhe `browser_first`, `browser_only`, `httpx_first`, `httpx_only`, `stealth_browser` ou `stealth_http`. Isso evita impor Chromium a páginas estáticas e ativa camuflagem profunda anti-automação nos domínios que exigem.
2. **Resiliência e Evasão Stealth**: HTTPX e Playwright contam com timeout, retry com backoff exponencial, injeção de scripts anti-automação (evasão de `navigator.webdriver`, plugins e languages simulados) e validação contra páginas de bloqueio (WAF).
3. **Controle responsável**: A CLI respeita `robots.txt` por padrão, limita concorrência e atraso por domínio e considera `Retry-After` quando o servidor sinaliza espera.

---

## 5. Preparação e Execução

### A. Listar Plugins Ativos
O `compsognathus` responde conforme o Domínio da URL base. Veja o que ele sabe extrair hoje:

```bash
comps plugins list
```

### B. Preparar o alvo
Crie um simples arquivo de texto (ex: `alvos.txt`) na raiz, adicionando uma URL de teste didática (suportada por um plugin de prateleira):

```text
https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
```

### C. Validação Segura (`--dry-run`)
O processo de verificação seca evita acionar servidores com requisições irrelevantes caso existam erros de digitação:

```bash
comps scrape alvos.txt --dry-run
```
Se tudo estiver ok, o output alertará quais URLs têm plugins validados para elas, sem baixar 1 Byte da web.

### D. Raspar o Dataset
Agora é pra valer. Vamos pedir ao framework que converta o HTML puro em um arquivo de dados tabulares ou focado em IA:

```bash
# Exportação clássica tabular (CSV, Parquet, SQLite)
comps scrape alvos.txt --format csv --output livros.csv

# Exportação para IA / RAG (Markdown estruturado com metadados)
comps scrape alvos.txt --format markdown --output livros.md
```
O console mostrará cada passo do download, e ao fim, os arquivos `livros.csv` (ou `.md`) e `livros.run.json` serão criados. O dataset terá as colunas (ex: Título, Preço, Disponibilidade, etc) definidas pelo criador do plugin, além dos metadados de auditoria.

Para coletas longas, use um diretório de job. O SQLite guarda o progresso e os HTMLs podem ser reaproveitados:

```bash
comps scrape alvos.txt --job-dir .jobs/livros --cache-html
comps scrape alvos.txt --job-dir .jobs/livros --resume
```

O `--force` ignora o HTML em cache. Para uma política diferente de acesso, use
`--robots ignore` somente quando isso for permitido pelos termos do alvo.

---

## 6. Validando e Inspecionando o Dataset

Durante extrações com centenas de URLs, sites podem ser alterados entre o começo e o fim do scraping, quebrando seletores de forma súbita. Para validar se os dados não voltaram preenchidos de vazios/nulos, use:

```bash
comps validate livros.csv
```
Este comando percorrerá as linhas e lançará avisos sobre campos ausentes. (Se adicionar `--fail-on-error`, o CI falhará se houver erros).

Para ver estatísticas reais da extração, você pode extrair um relatório HTML rico:

```bash
comps report livros.csv --html dashboard.html
```
Um arquivo `dashboard.html` foi gerado na mesma pasta, contendo amostras da base de dados e gráficos sobre as colunas mais sadias.

---

## 7. Criando seu próprio Plugin (Scaffold Inicial)

Quando você for tentar fazer isso com um domínio para o qual ainda não exista um plugin empacotado, o CLI ajuda a iniciar os arquivos no lugar exato, criando o `.py` inicial com o `@register`, bem como as estruturas de teste:

```bash
comps plugins new "novo-alvo.com.br"
```

O arquivo gerado em `compsognathus/plugins/novo-alvo.py` terá comentários úteis dizendo como prosseguir. 

> O Tutorial profundo de como extrair valores via JSON-LD e escrever este plugin está no material adicional em [`docs/writing-a-plugin.md`](docs/writing-a-plugin.md).

Plugins que precisam ser distribuídos separadamente podem usar entry points
Python. O contrato e o exemplo estão no mesmo guia, na seção **Plugin externo
instalável**. O fluxo continua sendo o mesmo: o plugin registra o domínio e
fornece apenas a lógica de extração.

---

## 8. Limpeza de Artefatos Locais e Troubleshooting

- **Travamentos no scraping**: Caso as requisições aparentem estar travadas, consulte o manifesto e o log para distinguir timeout, bloqueio e espera por domínio. Diminua `--concurrency`, `--domain-concurrency` ou aumente `--domain-delay` antes de tentar novamente.
- **Retomada**: Se a coleta foi iniciada com `--job-dir`, use o mesmo diretório e `--resume`. Não altere a lista de URLs entre as duas execuções; o job rejeita listas incompatíveis para evitar misturar datasets.
- **Desativação**: Para fechar o ambiente virtual do terminal quando terminar: `deactivate`.
- **Limpeza**: As saídas de `csv`, `parquet`, `jsonl` e arquivos temporários criados acidentalmente podem ser removidos normalmente. Nenhuma configuração global da sua máquina é alterada, os dados se mantém onde foram solicitados.

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

Em seguida, o download do Chromium precisa ser efetuado. Ele é o núcleo do navegador automatizado Playwright, essencial para os downloads de páginas complexas.

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
1. **Camada de renderização (`Playwright`)**: O sistema tenta em primeiro lugar acionar o Chromium para carregar a página tal como um navegador real, garantindo a carga de qualquer script e lidando com camadas passivas de firewalls (WAF).
2. **Camada HTTP direta (`HTTPX`)**: Se o Playwright lançar *Timeout* ou for bloqueado por alguma instabilidade na renderização do DOM, o sistema não cancela de imediato; ele usa o cliente `httpx` (suportando HTTP/2) como *fallback* secundário, na tentativa de extrair o dado de um esqueleto estático de resposta.
3. Se o limite de taxa de requisições (*Rate Limit*) ocorrer (bloqueio temporário), a ferramenta retentará com pequenos intervalos (*jitter*) antes de falhar permanentemente no URL em particular.

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
Agora é pra valer. Vamos pedir ao framework que converta o HTML puro em um arquivo de dados tabulares (ex: `.csv`). 

```bash
comps scrape alvos.txt --format csv --output livros.csv
```
O console mostrará cada passo do download, e ao fim, o arquivo `livros.csv` será criado com as colunas (ex: Título, Preço, Disponibilidade, etc) definidas pelo criador do plugin.

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

---

## 8. Limpeza de Artefatos Locais e Troubleshooting

- **Travamentos no scraping**: Caso as requisições aparentem estar travadas e os Playwrights fiquem em loop, o problema costuma ser limites duros IP-based. O sistema eventualmente estourará `TimeoutError` nas instâncias travadas e gravará o log. Diminua a `--concurrency`.
- **Desativação**: Para fechar o ambiente virtual do terminal quando terminar: `deactivate`.
- **Limpeza**: As saídas de `csv`, `parquet`, `jsonl` e arquivos temporários criados acidentalmente podem ser removidos normalmente. Nenhuma configuração global da sua máquina é alterada, os dados se mantém onde foram solicitados.

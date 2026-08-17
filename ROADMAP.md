# Roadmap do Compsognathus

Este roadmap prioriza melhorias com impacto direto em confiabilidade dos dados,
desempenho e robustez operacional. O objetivo não é transformar o
Compsognathus em um crawler generalista, mas fortalecer sua proposta: coletar
uma lista conhecida de URLs e produzir datasets estruturados e auditáveis.

## Princípios

- Manter o fluxo `download → parse → validação → exportação` fácil de entender.
- Adicionar abstrações somente quando resolvem um problema real do projeto.
- Preservar compatibilidade com os plugins e comandos existentes sempre que
  possível.
- Preferir comportamentos explícitos e resultados auditáveis.

## v1.4 — Contratos e eficiência

### 1. Validação tipada por plugin

Permitir que cada plugin declare, opcionalmente, um modelo Pydantic para seus
campos extraídos. A lista atual de campos obrigatórios continuará disponível
para manter compatibilidade.

**Entregas**

- Adicionar um modelo tipado opcional ao registro do plugin.
- Validar tipos, limites e formatos depois do parse.
- Converter erros do Pydantic em `parse_errors` auditáveis.
- Manter `schema=[...]` funcionando para plugins existentes.
- Atualizar o scaffolding e a documentação de criação de plugins.

**Concluído quando**

- Valores presentes, porém inválidos, fizerem `parse_ok=False`.
- Plugins antigos continuarem funcionando sem alteração.
- Houver testes para campos ausentes, tipos incorretos e restrições inválidas.

### 2. Política de download por plugin

Permitir que o plugin informe como seu domínio deve ser baixado, evitando o
custo de iniciar um navegador para páginas que funcionam com HTTP comum.

**Entregas**

- Criar uma política com estratégias `httpx_first`, `browser_first`,
  `httpx_only` e `browser_only`.
- Permitir timeout, seletor de prontidão e cabeçalhos específicos por plugin.
- Usar HTTPX primeiro nos plugins que extraem HTML ou JSON-LD estático.
- Reutilizar clientes HTTP e a instância do navegador durante o lote.
- Preservar a estratégia atual como padrão compatível durante a migração.

**Concluído quando**

- Plugins estáticos não iniciarem Chromium desnecessariamente.
- Uma coleta concorrente reutilizar recursos sem misturar sessões indevidamente.
- Testes cobrirem todas as estratégias e seus fallbacks.

### 3. Evidências de download mais completas

Ampliar `DownloadResult` e o dataset final para explicar melhor o que aconteceu
em cada URL.

**Entregas**

- Registrar status HTTP, URL final, duração e número de tentativas.
- Preservar o tipo estruturado do erro, além da mensagem legível.
- Registrar se o conteúdo veio de cache quando esse recurso estiver disponível.
- Incluir os novos metadados em `validate` e `report`.

**Concluído quando**

- Uma falha puder ser diagnosticada pelo dataset sem depender apenas do log.
- Relatórios antigos continuarem sendo aceitos.

## v1.5 — Coletas recuperáveis e responsáveis

### 4. Checkpoint e retomada

Persistir o progresso durante a execução para que interrupções não obriguem o
usuário a repetir todo o lote.

**Entregas**

- Criar um diretório de trabalho por execução.
- Persistir estados `pending`, `downloaded`, `parsed` e `failed` em SQLite.
- Adicionar `--job-dir` e `--resume`.
- Gravar cada resultado assim que ele for concluído.
- Fazer a exportação final de forma atômica.
- Detectar configurações incompatíveis ao retomar uma execução.

**Concluído quando**

- Uma execução interrompida puder continuar sem repetir URLs concluídas.
- Uma interrupção não corromper o dataset final nem o estado do trabalho.
- O comportamento estiver coberto por testes de interrupção e retomada.

### 5. Cache e deduplicação de URLs

Evitar downloads repetidos dentro do mesmo lote e permitir reaproveitar HTMLs
já coletados de forma explícita.

**Entregas**

- Remover duplicatas preservando a ordem original.
- Adicionar cache opcional dos HTMLs com metadados de origem e data.
- Oferecer opções equivalentes a `--cache-html` e `--force`.
- Invalidar ou ignorar entradas de cache incompatíveis ou corrompidas.

**Concluído quando**

- Uma URL repetida for baixada apenas uma vez por execução.
- O dataset indicar claramente quando um conteúdo veio do cache.

### 6. Controle por domínio

Substituir o jitter isolado por limites previsíveis que evitem rajadas contra
um mesmo site.

**Entregas**

- Separar concorrência global de concorrência por domínio.
- Garantir um intervalo mínimo configurável entre requisições do mesmo domínio.
- Respeitar `Retry-After` em respostas compatíveis.
- Aumentar o atraso diante de `429`, `503`, erros repetidos ou alta latência.
- Expor limites conservadores na CLI e na política do plugin.

**Concluído quando**

- Aumentar a concorrência global não provocar rajadas no mesmo domínio.
- Testes determinísticos comprovarem limites, espera e recuperação após erros.

### 7. Política explícita de `robots.txt`

Fazer o comportamento da ferramenta corresponder à orientação de uso
responsável apresentada na documentação.

**Entregas**

- Implementar modos explícitos para respeitar ou ignorar `robots.txt`.
- Documentar a escolha padrão e suas implicações.
- Registrar recusas por `robots.txt` como resultado auditável.
- Reutilizar a consulta por domínio durante o lote.

**Concluído quando**

- O usuário conseguir identificar por que uma URL não foi baixada.
- A política escolhida constar nos metadados da execução.

## v1.6 — Extensibilidade sustentável

### 8. Plugins instaláveis externamente

Permitir que plugins sejam distribuídos como pacotes Python sem exigir
alterações no repositório principal.

**Entregas**

- Descobrir plugins por entry points do Python.
- Manter os plugins internos e o decorador atual funcionando.
- Mostrar origem e versão em `comps plugins list`.
- Detectar conflitos de domínio com uma mensagem clara.
- Documentar como criar, testar e publicar um plugin externo.

**Concluído quando**

- Um pacote instalado separadamente puder registrar um domínio.
- A instalação e remoção do pacote atualizarem a lista de plugins sem editar o
  Compsognathus.

### 9. Manifesto da execução

Gerar um resumo estruturado do lote para complementar o dataset e os logs.

**Entregas**

- Registrar início, término, duração, configuração e versão do projeto.
- Contabilizar sucessos, falhas, retries, bytes e métodos de download.
- Produzir um arquivo lateral `*.run.json`.
- Incorporar essas métricas ao relatório HTML.

**Concluído quando**

- Duas execuções puderem ser comparadas sem interpretar logs textuais.
- O manifesto não incluir segredos presentes em cabeçalhos ou configurações.

## Fora do escopo

Não estão planejados enquanto a proposta do projeto continuar sendo a coleta
estruturada de URLs conhecidas:

- descoberta automática e navegação recursiva de links;
- engine de spiders e scheduler genérico;
- reescrita completa para Twisted ou `asyncio`;
- sistema amplo de middlewares e sinais;
- filas distribuídas;
- suporte genérico a FTP, S3, proxies ou autenticação complexa;
- mecanismos para contornar proteções rígidas ou políticas de acesso.

Esses recursos aumentariam muito a complexidade sem melhorar o principal caso
de uso do Compsognathus.

## Ordem recomendada

1. Validação tipada.
2. Política de download e reutilização de recursos.
3. Evidências de download.
4. Checkpoint e retomada.
5. Cache e deduplicação.
6. Controle por domínio e `robots.txt`.
7. Plugins externos.
8. Manifesto da execução.


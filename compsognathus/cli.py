"""
Interface de linha de comando (CLI) do Compsognathus.

Comandos disponíveis:
    comps scrape        — baixa URLs e exporta dados (Parquet, CSV, JSON, JSONL, SQLite)
    comps report        — exibe estatísticas e gera relatório HTML visual
    comps validate      — diagnostica qualidade e falhas de um dataset
    comps plugins list  — lista plugins registrados e seus schemas
    comps plugins new   — gera boilerplate para um novo plugin
"""
from __future__ import annotations

import logging
import re
from contextlib import closing
from html import escape
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

app = typer.Typer(
    name="comps",
    help="🦕 Compsognathus — Framework genérico de web scraping por plugins.",
    add_completion=False,
    rich_markup_mode="rich",
)
plugins_app = typer.Typer(help="Gerenciamento e criação de plugins.")
app.add_typer(plugins_app, name="plugins")

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    """Configura logging: console colorido (via rich) + arquivo compsognathus.log."""
    level = logging.DEBUG if verbose else logging.INFO
    file_handler = logging.FileHandler("compsognathus.log", encoding="utf-8", delay=True)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            RichHandler(console=console, show_path=False, markup=True),
            file_handler,
        ],
        force=True,
    )


def _read_urls(source: str) -> list[str]:
    """Lê URLs de um arquivo .txt ou de uma string de URL única."""
    source_clean = source.strip().strip('"\'')
    if urlparse(source_clean).scheme:
        urls = [source_clean]
    else:
        path = Path(source_clean)
        if not path.exists():
            console.print(f"[red]❌ Arquivo não encontrado: {source}[/red]")
            raise typer.Exit(1)

        raw_lines = path.read_text(encoding="utf-8").splitlines()
        urls = []
        for line in raw_lines:
            clean = line.strip().strip('"\'')
            # Ignora linhas vazias e comentários iniciados por '#' ou '//'
            if clean and not clean.startswith("#") and not clean.startswith("//"):
                urls.append(clean)

    if not urls:
        console.print("[red]❌ Nenhuma URL válida encontrada no arquivo.[/red]")
        raise typer.Exit(1)

    invalid = [
        url for url in urls
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc
    ]
    if invalid:
        console.print(f"[red]❌ URL(s) inválida(s): {', '.join(invalid[:3])}[/red]")
        raise typer.Exit(1)

    return urls


# ── Comando: scrape ───────────────────────────────────────────────────────────

@app.command()
def scrape(
    source: str = typer.Argument(..., help="Arquivo .txt com URLs ou uma URL direta."),
    output: Path = typer.Option(Path("output.parquet"), "--output", "-o", help="Arquivo de saída (parquet, csv, json, jsonl, sqlite)."),
    fmt: str = typer.Option("parquet", "--format", "-f", help="Formato: 'parquet', 'csv', 'json', 'jsonl', 'sqlite'."),
    concurrency: int = typer.Option(1, "--concurrency", "-c", min=1, help="Número de downloads simultâneos em paralelo."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Exibe logs detalhados."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Valida URLs e plugins disponíveis sem realizar downloads."),
) -> None:
    """Raspa URLs e exporta dados estruturados.

    Exemplos:
        comps scrape links.txt --output dados.parquet
        comps scrape links.txt --format jsonl --output dados.jsonl
        comps scrape links.txt --format sqlite --output banco.db --concurrency 3
        comps scrape links.txt --dry-run
    """
    _setup_logging(verbose)
    from urllib.parse import urlparse
    from compsognathus.core.registry import get_parser
    from compsognathus.scraper import scrape as _scrape

    import compsognathus.plugins  # noqa: F401

    urls = _read_urls(source)

    known_suffixes = {
        ".parquet": "parquet",
        ".pq": "parquet",
        ".csv": "csv",
        ".json": "json",
        ".jsonl": "jsonl",
        ".ndjson": "jsonl",
        ".db": "sqlite",
        ".sqlite": "sqlite",
        ".sqlite3": "sqlite",
    }
    suffix_format = known_suffixes.get(output.suffix.lower())
    if fmt.lower() == "parquet" and suffix_format and suffix_format != "parquet":
        fmt = suffix_format
        console.print(f"[dim]Formato inferido pela extensão: {fmt}[/dim]")

    if dry_run:
        console.print(f"\n[bold yellow]🔍 DRY RUN — Validação de URLs ({len(urls)} URLs)[/bold yellow]\n")
        table = Table(title="Simulação de Scraping", show_lines=True)
        table.add_column("URL", style="cyan", max_width=40, no_wrap=True)
        table.add_column("Domínio", style="dim")
        table.add_column("Status Plugin", style="bold")
        table.add_column("Módulo", style="green")

        valid_count = 0
        for url in urls:
            domain = urlparse(url).netloc.lower()
            try:
                fn = get_parser(url)
                status = "[green]✅ Disponível[/green]"
                module = fn.__module__.split(".")[-1]
                valid_count += 1
            except ValueError:
                status = "[red]❌ Não suportado[/red]"
                module = "–"

            table.add_row(url, domain, status, module)

        console.print(table)
        console.print(
            f"\n[dim]Resumo do Dry-Run: {valid_count}/{len(urls)} URL(s) possuem plugins compatíveis.[/dim]\n"
        )
        return

    console.print(f"\n[bold cyan]🦕 Compsognathus[/bold cyan] — {len(urls)} URL(s) para raspar (threads={concurrency})\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Raspando...", total=len(urls))
        status_msgs: list[str] = []

        def _on_progress(current: int, total: int, msg: str) -> None:
            status_msgs.append(msg)
            progress.update(task, completed=current, description=msg[:60])

        df = _scrape(
            urls,
            output_path=output,
            fmt=fmt,
            concurrency=concurrency,
            progress_callback=_on_progress,
        )

    if df.empty:
        console.print("[red]Nenhum dado extraído.[/red]")
        raise typer.Exit(1)

    ok = df["parse_ok"].sum() if "parse_ok" in df.columns else len(df)
    console.print(f"\n[green]✅ Concluído![/green] {ok}/{len(df)} registros com sucesso")
    console.print(f"[dim]Exportado para: {output} (formato: {fmt})[/dim]\n")

    _print_preview(df, max_rows=5)


# ── Comando: validate ─────────────────────────────────────────────────────────

def _load_dataframe(file: Path):
    """Carrega um dataset suportado pela CLI."""
    import pandas as pd
    import sqlite3

    if not file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file}")
    if file.suffix in (".parquet", ".pq"):
        return pd.read_parquet(file)
    if file.suffix == ".csv":
        return pd.read_csv(file)
    if file.suffix in (".json", ".jsonl"):
        return pd.read_json(file, lines=file.suffix == ".jsonl")
    if file.suffix in (".db", ".sqlite", ".sqlite3"):
        with closing(sqlite3.connect(file)) as conn:
            return pd.read_sql_query("SELECT * FROM scraped_data", conn)
    return pd.read_parquet(file)


def _quality_bool_series(df, column: str, default: bool):
    import pandas as pd

    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)
    values = df[column]
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "sim"})


@app.command()
def validate(
    file: Path = typer.Argument(..., help="Arquivo de dados a validar."),
    fail_on_error: bool = typer.Option(False, "--fail-on-error", help="Sai com código 1 se houver falhas."),
) -> None:
    """Diagnostica downloads, parsing e erros registrados no dataset."""
    from collections import Counter

    try:
        df = _load_dataframe(file)
    except Exception as exc:
        console.print(f"[red]❌ Erro ao ler o arquivo: {exc}[/red]")
        raise typer.Exit(1)

    parse_ok = _quality_bool_series(df, "parse_ok", True)
    download_ok = _quality_bool_series(df, "download_ok", True)
    parse_failures = int((~parse_ok).sum())
    download_failures = int((~download_ok).sum())

    errors = Counter()
    if "parse_errors" in df.columns:
        for value in df["parse_errors"].dropna():
            errors.update(item.strip() for item in str(value).split(",") if item.strip())

    console.print()
    console.print(f"[bold cyan]🔎 Validação:[/bold cyan] {file.name}")
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("Total de registros", str(len(df)))
    table.add_row("Downloads com falha", str(download_failures))
    table.add_row("Parses com falha", str(parse_failures))
    table.add_row("Registros completos", f"{int(parse_ok.sum())}/{len(df)}")
    console.print(table)

    if errors:
        console.print()
        console.print("[bold]Principais erros:[/bold]")
        error_table = Table()
        error_table.add_column("Erro")
        error_table.add_column("Ocorrências", justify="right")
        for error, count in errors.most_common(10):
            error_table.add_row(error, str(count))
        console.print(error_table)

    has_errors = download_failures > 0 or parse_failures > 0
    status = "[red]❌ Dataset contém falhas[/red]" if has_errors else "[green]✅ Dataset íntegro[/green]"
    console.print()
    console.print(status)
    console.print()
    if has_errors and fail_on_error:
        raise typer.Exit(1)


# ── Comando: report ───────────────────────────────────────────────────────────

@app.command()
def report(
    file: Path = typer.Argument(..., help="Arquivo de dados (parquet, csv, json, sqlite)."),
    html_out: Optional[Path] = typer.Option(None, "--html", "-h", help="Exporta relatório visual HTML no caminho especificado."),
) -> None:
    """Exibe estatísticas de um arquivo de dados e opcionalmente gera um relatório HTML visual.

    Exemplos:
        comps report dados.parquet
        comps report dados.parquet --html relatorio.html
    """
    import pandas as pd
    import sqlite3

    if not file.exists():
        console.print(f"[red]❌ Arquivo não encontrado: {file}[/red]")
        raise typer.Exit(1)

    try:
        if file.suffix in (".parquet", ".pq"):
            df = pd.read_parquet(file)
        elif file.suffix == ".csv":
            df = pd.read_csv(file)
        elif file.suffix in (".json", ".jsonl"):
            df = pd.read_json(file, lines=file.suffix == ".jsonl")
        elif file.suffix in (".db", ".sqlite", ".sqlite3"):
            with closing(sqlite3.connect(file)) as conn:
                df = pd.read_sql_query("SELECT * FROM scraped_data", conn)
        else:
            # Tenta parquet primeiro por padrão
            df = pd.read_parquet(file)
    except Exception as exc:
        console.print(f"[red]❌ Erro ao ler o arquivo: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]📊 Relatório:[/bold cyan] {file.name}\n")

    total = len(df)
    ok = int(df["parse_ok"].sum()) if "parse_ok" in df.columns else total
    sites = df["site"].unique().tolist() if "site" in df.columns else []

    metrics = Table(show_header=False, box=None, padding=(0, 2))
    metrics.add_row("Total de registros", str(total))
    metrics.add_row("Registros completos", f"{ok}/{total} ({ok/total*100:.0f}%)" if total > 0 else "0/0")
    metrics.add_row("Sites coletados", ", ".join(str(s) for s in sites))
    metrics.add_row("Colunas", str(len(df.columns)))
    console.print(metrics)

    numeric_cols = df.select_dtypes(include="number").columns
    price_cols = [c for c in numeric_cols if "preco" in c or "salario" in c or "price" in c]
    if price_cols:
        console.print("\n[bold]Estatísticas numéricas:[/bold]")
        stats = Table()
        stats.add_column("Campo")
        stats.add_column("Média", justify="right")
        stats.add_column("Mín", justify="right")
        stats.add_column("Máx", justify="right")
        for col in price_cols:
            col_data = df[col].dropna()
            if len(col_data) > 0:
                stats.add_row(
                    col,
                    f"{col_data.mean():,.2f}",
                    f"{col_data.min():,.2f}",
                    f"{col_data.max():,.2f}",
                )
        console.print(stats)

    console.print("\n[bold]Prévia (top 10):[/bold]")
    _print_preview(df, max_rows=10)

    # Exportação HTML se solicitada
    if html_out:
        _export_html_report(df, file.name, html_out)
        console.print(f"\n[green]✨ Relatório HTML gerado em:[/green] {html_out}\n")


# ── Comando: plugins list & new ───────────────────────────────────────────────

@plugins_app.command("list")
def plugins_list() -> None:
    """Lista todos os plugins registrados e seus campos."""
    from compsognathus.core.registry import list_plugins
    import compsognathus.plugins  # noqa: F401

    plugins = list_plugins()
    if not plugins:
        console.print("[yellow]Nenhum plugin registrado.[/yellow]")
        return

    table = Table(title="🦕 Plugins registrados", show_lines=True)
    table.add_column("Domínio", style="cyan")
    table.add_column("Campos extraídos", style="green")
    table.add_column("Descrição", style="dim")

    for p in plugins:
        table.add_row(p["domain"], p["schema"], p["description"])

    console.print(table)
    console.print(f"\n[dim]Total: {len(plugins)} plugin(s) • Para criar um novo: comps plugins new <dominio>[/dim]\n")


@plugins_app.command("new")
def plugins_new(
    domain: str = typer.Argument(..., help="Domínio do novo plugin (ex: olx.com.br)."),
) -> None:
    """Gera automaticamente a estrutura inicial para um novo plugin (Scaffolding).

    Exemplo:
        comps plugins new olx.com.br
    """
    from urllib.parse import urlparse

    raw_domain = domain.strip()
    parsed = urlparse(raw_domain if "://" in raw_domain else f"//{raw_domain}")
    clean_domain = (parsed.hostname or "").lower().rstrip(".")
    if clean_domain.startswith("www."):
        clean_domain = clean_domain[4:]

    has_extra_url_parts = bool(parsed.path and parsed.path != "/") or bool(parsed.query or parsed.fragment)
    valid_labels = clean_domain.split(".")
    is_valid_domain = (
        len(valid_labels) >= 2
        and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in valid_labels)
    )
    if has_extra_url_parts or not is_valid_domain:
        console.print(f"[red]❌ Domínio inválido: {domain}[/red]")
        raise typer.Exit(1)

    # Nome do módulo python: olx.com.br -> olx
    mod_name = clean_domain.split(".")[0].replace("-", "_")

    plugin_file = Path("compsognathus") / "plugins" / f"{mod_name}.py"
    fixture_file = Path("tests") / "fixtures" / f"{mod_name}_sample.html"

    if plugin_file.exists():
        console.print(f"[yellow]⚠️ O arquivo de plugin já existe em: {plugin_file}[/yellow]")
        raise typer.Exit(1)

    # 1. Cria plugin Python
    plugin_code = f'''"""
Plugin: {clean_domain}
Domínio: Personalizado
Extrai: titulo, preco, descricao
"""
from bs4 import BeautifulSoup
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


@register("{clean_domain}", schema=["titulo", "preco", "descricao"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser para {clean_domain}."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # Título
    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else None
    if not titulo:
        errors.append("titulo")

    # Preço
    preco_el = soup.select_one(".price")
    preco = None
    if preco_el:
        try:
            import re
            m = re.search(r"[\\d.]+", preco_el.get_text())
            preco = float(m.group(0)) if m else None
        except Exception:
            pass
    if preco is None:
        errors.append("preco")

    # Descrição
    desc_el = soup.select_one(".description")
    descricao = desc_el.get_text(strip=True) if desc_el else None

    return ScrapedRecord(
        url=url,
        site="{mod_name}",
        fields={{
            "titulo": titulo,
            "preco": preco,
            "descricao": descricao,
        }},
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
'''
    plugin_file.parent.mkdir(parents=True, exist_ok=True)
    plugin_file.write_text(plugin_code, encoding="utf-8")

    # 2. Cria fixture sintética
    fixture_code = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Anúncio Exemplo - {clean_domain}</title>
</head>
<body>
  <h1>Título de Exemplo</h1>
  <span class="price">99.90</span>
  <div class="description">Descrição fictícia para teste.</div>
</body>
</html>
'''
    fixture_file.parent.mkdir(parents=True, exist_ok=True)
    fixture_file.write_text(fixture_code, encoding="utf-8")

    init_file = Path("compsognathus") / "plugins" / "__init__.py"
    import_line = f"import compsognathus.plugins.{mod_name}  # noqa: F401"
    init_text = init_file.read_text(encoding="utf-8") if init_file.exists() else ""
    if import_line not in init_text:
        init_file.parent.mkdir(parents=True, exist_ok=True)
        init_file.write_text(init_text.rstrip() + "\n" + import_line + "\n", encoding="utf-8")

    test_file = Path("tests") / f"test_{mod_name}.py"
    test_code = f'''from pathlib import Path

from compsognathus.plugins.{mod_name} import parse


def test_{mod_name}_fixture():
    fixture = Path(__file__).parent / "fixtures" / "{mod_name}_sample.html"
    html = fixture.read_text(encoding="utf-8")
    record = parse(html, "https://{clean_domain}/item/1")
    assert record.fields["titulo"]
'''
    if not test_file.exists():
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(test_code, encoding="utf-8")

    console.print(f"\n[bold green]✨ Scaffold criado com sucesso para '{clean_domain}'![/bold green]\n")
    console.print(f"  📄 Plugin criado: [cyan]{plugin_file}[/cyan]")
    console.print(f"  🧪 Fixture criada: [cyan]{fixture_file}[/cyan]\n")
    console.print(f"  🧩 Import registrado em: [cyan]{init_file}[/cyan]")
    console.print(f"  🧪 Teste criado: [cyan]{test_file}[/cyan]\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_preview(df, max_rows: int = 5) -> None:
    """Exibe as primeiras linhas do DataFrame como tabela no terminal."""
    import pandas as pd

    priority_cols = ["site", "url", "parse_ok"]
    other_cols = [c for c in df.columns if c not in priority_cols and c not in ("data_coleta", "parse_errors")]
    display_cols = priority_cols + other_cols[:6]
    display_cols = [c for c in display_cols if c in df.columns]

    preview = df[display_cols].head(max_rows)

    table = Table(show_lines=False)
    for col in preview.columns:
        table.add_column(col, max_width=30, no_wrap=True)

    for _, row in preview.iterrows():
        table.add_row(*[str(v)[:28] if pd.notna(v) else "–" for v in row])

    console.print(table)


def _export_html_report(df, filename: str, output_path: Path) -> None:
    """Gera um relatório HTML visual em página única auto-contida."""
    total = len(df)
    ok_count = int(df["parse_ok"].sum()) if "parse_ok" in df.columns else total
    taxa_ok = (ok_count / total * 100) if total > 0 else 0

    table_rows: list[str] = []
    for _, row in df.head(20).iterrows():
        cells: list[str] = []
        for col in df.columns[:8]:
            value = row[col]
            val = "-" if value is None else str(value)
            cells.append(f"<td>{escape(val[:40])}</td>")
        table_rows.append(f"<tr>{''.join(cells)}</tr>")
    table_rows_html = "".join(table_rows)

    headers_html = "".join(f"<th>{escape(str(col))}</th>" for col in df.columns[:8])
    safe_filename = escape(filename)

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Relatório Compsognathus - {safe_filename}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 2rem; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid #334155; }}
        h1 {{ color: #38bdf8; margin-top: 0; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }}
        .metric {{ background: #0f172a; padding: 1rem; border-radius: 8px; text-align: center; border: 1px solid #334155; }}
        .metric .val {{ font-size: 1.8rem; font-weight: bold; color: #4ade80; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.9rem; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; }}
        tr:hover {{ background: #334155; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🦕 Compsognathus — Relatório do Dataset</h1>
        <p style="color: #94a3b8">Arquivo analisado: <strong>{safe_filename}</strong></p>
        <div class="grid">
            <div class="metric"><div>Total de Registros</div><div class="val">{total}</div></div>
            <div class="metric"><div>Taxa de Sucesso</div><div class="val">{taxa_ok:.1f}%</div></div>
            <div class="metric"><div>Total de Colunas</div><div class="val">{len(df.columns)}</div></div>
        </div>
    </div>
    <div class="card">
        <h2>Prévia dos Dados (Top 20)</h2>
        <div style="overflow-x: auto;">
            <table>
                <thead><tr>{headers_html}</tr></thead>
                <tbody>{table_rows_html}</tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")


if __name__ == "__main__":
    app()

"""
Interface de linha de comando (CLI) do Compsognathus.

Comandos disponíveis:
    comps scrape   — baixa URLs e exporta dados estruturados
    comps report   — exibe estatísticas de um arquivo .parquet
    comps plugins  — lista plugins registrados e seus campos

Uso:
    comps scrape links.txt --output dados.parquet
    comps report dados.parquet
    comps plugins list
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Inicialização do CLI — typer cria o app principal e o subgrupo 'plugins'
app = typer.Typer(
    name="comps",
    help="🦕 Compsognathus — Framework genérico de web scraping por plugins.",
    add_completion=False,
    rich_markup_mode="rich",
)
plugins_app = typer.Typer(help="Gerenciamento de plugins.")
app.add_typer(plugins_app, name="plugins")

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    """Configura logging: console colorido (via rich) + arquivo compsognathus.log."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            RichHandler(console=console, show_path=False, markup=True),
            logging.FileHandler("compsognathus.log", encoding="utf-8"),
        ],
    )


def _read_urls(source: str) -> list[str]:
    """Lê URLs de um arquivo .txt ou de uma string de URL única.

    Suporta:
        - Arquivo de texto (uma URL por linha)
        - URL direta (começa com http:// ou https://)
    """
    if source.startswith("http://") or source.startswith("https://"):
        return [source.strip()]

    path = Path(source)
    if not path.exists():
        console.print(f"[red]❌ Arquivo não encontrado: {source}[/red]")
        raise typer.Exit(1)

    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        console.print("[red]❌ Nenhuma URL encontrada no arquivo.[/red]")
        raise typer.Exit(1)

    return urls


# ── Comando: scrape ───────────────────────────────────────────────────────────

@app.command()
def scrape(
    source: str = typer.Argument(..., help="Arquivo .txt com URLs ou uma URL direta."),
    output: Path = typer.Option(Path("output.parquet"), "--output", "-o", help="Arquivo de saída (.parquet ou .csv)."),
    fmt: str = typer.Option("parquet", "--format", "-f", help="Formato: 'parquet' ou 'csv'."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Exibe logs detalhados."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Valida URLs e plugins disponíveis sem realizar downloads."),
) -> None:
    """Raspa URLs e exporta dados estruturados em .parquet ou .csv.

    Exemplos:
        comps scrape links.txt --output dados.parquet
        comps scrape https://www.zapimoveis.com.br/imovel/... -o single.csv -f csv
        comps scrape links.txt --dry-run
    """
    _setup_logging(verbose)
    from urllib.parse import urlparse
    from compsognathus.core.registry import get_parser
    from compsognathus.scraper import scrape as _scrape

    # Garante que plugins estejam auto-registrados
    import compsognathus.plugins  # noqa: F401

    urls = _read_urls(source)

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

    console.print(f"\n[bold cyan]🦕 Compsognathus[/bold cyan] — {len(urls)} URL(s) para raspar\n")

    # Barra de progresso visual (rich) com spinner, barra e tempo decorrido
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

        df = _scrape(urls, output_path=output, fmt=fmt, progress_callback=_on_progress)

    # Resumo final
    if df.empty:
        console.print("[red]Nenhum dado extraído.[/red]")
        raise typer.Exit(1)

    ok = df["parse_ok"].sum() if "parse_ok" in df.columns else len(df)
    console.print(f"\n[green]✅ Concluído![/green] {ok}/{len(df)} registros com sucesso")
    console.print(f"[dim]Exportado para: {output}[/dim]\n")

    # Prévia da tabela (top 5 linhas)
    _print_preview(df, max_rows=5)


# ── Comando: report ───────────────────────────────────────────────────────────

@app.command()
def report(
    file: Path = typer.Argument(..., help="Arquivo .parquet gerado pelo comando scrape."),
) -> None:
    """Exibe estatísticas e prévia de um arquivo de dados gerado.

    Exemplo:
        comps report dados.parquet
    """
    import pandas as pd

    if not file.exists():
        console.print(f"[red]❌ Arquivo não encontrado: {file}[/red]")
        raise typer.Exit(1)

    try:
        df = pd.read_parquet(file)
    except Exception as exc:
        console.print(f"[red]❌ Erro ao ler o arquivo: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]📊 Relatório:[/bold cyan] {file.name}\n")

    # ── Métricas de qualidade ─────────────────────────────────────────────────
    total = len(df)
    ok = int(df["parse_ok"].sum()) if "parse_ok" in df.columns else total
    sites = df["site"].unique().tolist() if "site" in df.columns else []

    metrics = Table(show_header=False, box=None, padding=(0, 2))
    metrics.add_row("Total de registros", str(total))
    metrics.add_row("Registros completos", f"{ok}/{total} ({ok/total*100:.0f}%)")
    metrics.add_row("Sites coletados", ", ".join(sites))
    metrics.add_row("Colunas", str(len(df.columns)))
    console.print(metrics)

    # Estatísticas numéricas para campos de preço (se existirem)
    numeric_cols = df.select_dtypes(include="number").columns
    price_cols = [c for c in numeric_cols if "preco" in c or "salario" in c]
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

    # Prévia dos dados
    console.print("\n[bold]Prévia (top 10):[/bold]")
    _print_preview(df, max_rows=10)


# ── Comando: plugins list ─────────────────────────────────────────────────────

@plugins_app.command("list")
def plugins_list() -> None:
    """Lista todos os plugins registrados e seus campos."""
    from compsognathus.core.registry import list_plugins

    # Garante que os plugins estejam registrados
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
    console.print(f"\n[dim]Total: {len(plugins)} plugin(s) • Para criar um novo: docs/writing-a-plugin.md[/dim]\n")


# ── Helper: prévia de tabela ──────────────────────────────────────────────────

def _print_preview(df, max_rows: int = 5) -> None:
    """Exibe as primeiras linhas do DataFrame como tabela no terminal."""
    import pandas as pd

    # Seleciona as colunas mais relevantes para exibir
    priority_cols = ["site", "url", "parse_ok"]
    other_cols = [c for c in df.columns if c not in priority_cols and c not in ("data_coleta", "parse_errors")]
    display_cols = priority_cols + other_cols[:6]  # máx 9 colunas na tela
    display_cols = [c for c in display_cols if c in df.columns]

    preview = df[display_cols].head(max_rows)

    table = Table(show_lines=False)
    for col in preview.columns:
        table.add_column(col, max_width=30, no_wrap=True)

    for _, row in preview.iterrows():
        table.add_row(*[str(v)[:28] if pd.notna(v) else "–" for v in row])

    console.print(table)


# ── Ponto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()

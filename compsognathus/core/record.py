"""
Modelo de dados genérico para qualquer item raspado.

ScrapedRecord não assume domínio — cada plugin define seus próprios campos
dentro do dicionário `fields`. Isso permite usar o mesmo framework para
imóveis, vagas de emprego, e-commerce ou qualquer outro site.

Campos fixos (sempre presentes):
    url, site, data_coleta, parse_ok, parse_errors

Campos dinâmicos (definidos por cada plugin):
    fields  →  ex: {"preco": 450000, "area": 80} ou {"cargo": "Dev", "salario": 8000}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ScrapedRecord(BaseModel):
    """Registro universal de um item raspado de qualquer site.

    O campo `fields` é livre: cada plugin decide quais chaves inserir.
    Isso torna o modelo genérico sem sacrificar estrutura ou validação.

    Exemplo de uso pelos plugins:
        return ScrapedRecord(
            url=url,
            site="mercadolivre",
            fields={"produto": "MacBook", "preco": 12999.0},
            parse_ok=True,
        )
    """

    url: str            # URL original da página raspada
    site: str           # Identificador curto do site (ex: "zapimoveis", "catho")

    # Timestamp UTC da coleta — gerado automaticamente se não fornecido
    data_coleta: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Dados extraídos — formato livre definido por cada plugin
    # why: dict[str, Any] em vez de campos fixos para suportar qualquer domínio
    fields: dict[str, Any] = Field(default_factory=dict)

    # Metadados de qualidade do parse
    parse_ok: bool = True                          # False se campo obrigatório falhou
    parse_errors: list[str] = Field(               # Campos que não puderam ser extraídos
        default_factory=list
    )

    model_config = {"str_strip_whitespace": True}

    def get(self, key: str, default: Any = None) -> Any:
        """Atalho para acessar campos dinâmicos: record.get('preco')."""
        return self.fields.get(key, default)

"""
Auto-importa todos os plugins para que se registrem via @register.

Cada arquivo de plugin usa o decorator @register para se cadastrar
no registry global ao ser importado. Basta adicionar o import aqui
para ativar um novo plugin.

PLUGIN HOOK: adicione o import do seu plugin neste arquivo.
"""

# Plugins bundled — 3 domínios distintos como demonstração
import compsognathus.plugins.zapimoveis   # noqa: F401  (imobiliário)
import compsognathus.plugins.vivareal     # noqa: F401  (imobiliário)
import compsognathus.plugins.mercadolivre # noqa: F401  (e-commerce)
import compsognathus.plugins.catho        # noqa: F401  (vagas de emprego)
import compsognathus.plugins.books_toscrape # noqa: F401 (e-commerce / livros)

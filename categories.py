"""Descubrimiento y aplanado del árbol de categorías de VTEX."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from .client import JumboClient
from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class Category:
    id: int
    name: str
    url: str
    has_children: bool
    children: List["Category"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children


def _parse_node(node: dict) -> Category:
    children = [_parse_node(c) for c in node.get("children", []) or []]
    return Category(
        id=node["id"],
        name=node.get("name", ""),
        url=node.get("url", ""),
        has_children=bool(node.get("hasChildren")),
        children=children,
    )


def fetch_category_tree(client: JumboClient, config: Config) -> List[Category]:
    """Trae el árbol completo de departamentos -> categorías -> subcategorías."""
    logger.info("Obteniendo árbol de categorías…")
    raw = client.get_json(config.category_tree_url) or []
    tree = [_parse_node(n) for n in raw]
    logger.info("Departamentos raíz encontrados: %d", len(tree))
    return tree


def iter_leaf_categories(tree: List[Category]):
    """Recorre el árbol y entrega solo las hojas (categorías sin hijas).

    Trabajar a nivel de hoja reduce el solapamiento y, sobre todo, mantiene
    cada consulta por debajo del tope de offset (max_offset) que impone VTEX.
    """
    for cat in tree:
        if cat.is_leaf:
            yield cat
        else:
            yield from iter_leaf_categories(cat.children)


def flatten_all_categories(tree: List[Category]):
    """Entrega TODAS las categorías (incluidas las intermedias). Útil para
    construir el 'category path' o como respaldo si una hoja viniera vacía."""
    for cat in tree:
        yield cat
        if cat.children:
            yield from flatten_all_categories(cat.children)

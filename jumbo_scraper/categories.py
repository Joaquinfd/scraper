"""Descubrimiento del árbol de categorías vía Constructor.io /browse/groups."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from .client import JumboClient
from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class Category:
    id: str          # Constructor.io group_id, e.g. "74"
    name: str
    has_children: bool
    children: List["Category"] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children


def _parse_group(node: dict) -> Category:
    children = [_parse_group(c) for c in node.get("children", []) or []]
    return Category(
        id=str(node["group_id"]),
        name=node.get("display_name", ""),
        has_children=bool(children),
        children=children,
    )


def fetch_category_tree(client: JumboClient, config: Config) -> List[Category]:
    """Devuelve todos los departamentos con sus subcategorías (hijos directos)."""
    logger.info("Obteniendo árbol de categorías…")
    data = client.get_json(
        config.groups_url,
        {"key": config.api_key, "section": config.section},
    ) or {}
    groups = data.get("response", {}).get("groups", [])
    tree = [_parse_group(g) for g in groups]
    logger.info("Departamentos raíz encontrados: %d", len(tree))
    return tree


def iter_leaf_categories(tree: List[Category]):
    """Recorre el árbol y entrega solo las hojas (categorías sin hijas)."""
    for cat in tree:
        if cat.is_leaf:
            yield cat
        else:
            yield from iter_leaf_categories(cat.children)


def flatten_all_categories(tree: List[Category]):
    """Entrega TODAS las categorías, incluidas las intermedias."""
    for cat in tree:
        yield cat
        if cat.children:
            yield from flatten_all_categories(cat.children)

"""Paginación de productos por categoría usando Constructor.io /browse/group_id."""

from __future__ import annotations

import logging
import math
from typing import Iterator, Optional

from .categories import Category
from .client import JumboClient
from .config import Config

logger = logging.getLogger(__name__)


def iter_category_products(
    client: JumboClient,
    config: Config,
    category: Category,
) -> Iterator[dict]:
    """Itera todos los productos de una categoría, paginando de a page_size.

    Constructor.io no impone el tope de offset de VTEX, por lo que la
    paginación avanza hasta que el servidor no devuelve más resultados.
    """
    page = 1
    last_page: Optional[int] = None

    while True:
        params = {
            "key": config.api_key,
            "section": config.section,
            "num_results_per_page": config.page_size,
            "page": page,
        }
        try:
            data = client.get_json(
                f"{config.browse_url}/{category.id}", params
            ) or {}
        except Exception as exc:  # noqa: BLE001
            logger.error("Categoría '%s' (id=%s) [pág. %s] falló: %s",
                         category.name, category.id, page, exc)
            break

        resp = data.get("response", {})

        if last_page is None:
            total = resp.get("total_num_results") or 0
            last_page = math.ceil(total / config.page_size) if total else 1
            logger.info("Categoría '%s' (id=%s): %s productos (~%s páginas)",
                        category.name, category.id, total, last_page)

        results = resp.get("results") or []
        if not results:
            break

        for result in results:
            yield result["data"]

        if page >= last_page or len(results) < config.page_size:
            break

        page += 1

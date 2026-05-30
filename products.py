"""Paginación de productos por categoría usando la API clásica de VTEX."""

from __future__ import annotations

import logging
from typing import Iterator, List, Optional

from .categories import Category
from .client import JumboClient
from .config import Config

logger = logging.getLogger(__name__)


def _search_params(config: Config, category_id: int, _from: int, _to: int,
                   brand_id: Optional[int] = None) -> dict:
    # fq=C:/<id>/  filtra por categoría ; fq=B:<id> filtra por marca.
    fq = [f"C:/{category_id}/"]
    if brand_id is not None:
        fq.append(f"B:{brand_id}")
    params = {
        "fq": fq,
        "_from": _from,
        "_to": _to,
        "sc": config.sales_channel,
    }
    return params


def iter_category_products(
    client: JumboClient,
    config: Config,
    category: Category,
) -> Iterator[dict]:
    """Itera TODOS los productos de una categoría, paginando de a page_size.

    Maneja el tope de offset de VTEX (max_offset). Si una categoría supera ese
    tope, intenta subdividir por marca para no perder productos.
    """
    yielded = 0
    offset = 0
    total: Optional[int] = None

    while offset < config.max_offset:
        _from = offset
        _to = min(offset + config.page_size - 1, config.max_offset - 1)
        params = _search_params(config, category.id, _from, _to)

        try:
            batch, reported_total = client.get_with_range(config.search_url, params)
        except Exception as exc:  # noqa: BLE001
            logger.error("Categoría %s [%s-%s] falló: %s",
                         category.id, _from, _to, exc)
            break

        if total is None and reported_total is not None:
            total = reported_total
            logger.info("Categoría '%s' (id=%s): %s productos reportados",
                        category.name, category.id, total)

        if not batch:
            break

        for product in batch:
            yield product
            yielded += 1

        offset += config.page_size

        if len(batch) < config.page_size:
            break  # última página

    # ¿Categoría con más productos que el tope de offset? Subdividir por marca.
    if total is not None and total > config.max_offset:
        logger.warning(
            "Categoría '%s' (id=%s) supera el tope de %s (total=%s). "
            "Subdividiendo por marca…",
            category.name, category.id, config.max_offset, total,
        )
        yield from _iter_by_brand(client, config, category)


def _iter_by_brand(client: JumboClient, config: Config, category: Category) -> Iterator[dict]:
    """Recorre la categoría marca por marca para sortear el tope de offset."""
    brands = _facet_brands(client, config, category)
    if not brands:
        logger.warning("Sin facetas de marca para categoría %s; algunos "
                       "productos podrían quedar fuera.", category.id)
        return
    for brand_id in brands:
        offset = 0
        while offset < config.max_offset:
            _from = offset
            _to = min(offset + config.page_size - 1, config.max_offset - 1)
            params = _search_params(config, category.id, _from, _to, brand_id=brand_id)
            try:
                batch = client.get_json(config.search_url, params) or []
            except Exception as exc:  # noqa: BLE001
                logger.error("Marca %s en categoría %s falló: %s",
                             brand_id, category.id, exc)
                break
            if not batch:
                break
            for product in batch:
                yield product
            offset += config.page_size
            if len(batch) < config.page_size:
                break


def _facet_brands(client: JumboClient, config: Config, category: Category) -> List[int]:
    """Obtiene los IDs de marca disponibles dentro de una categoría vía facetas."""
    url = f"{config.base_url}/api/catalog_system/pub/facets/search/?map=c"
    # La API de facetas acepta el path de categoría; usamos el id como filtro fq.
    params = {"fq": f"C:/{category.id}/", "sc": config.sales_channel}
    try:
        data = client.get_json(url, params) or {}
    except Exception:  # noqa: BLE001
        return []
    brand_ids: List[int] = []
    for facet in (data.get("Brands") or []):
        # Cada faceta trae un 'Link'/'Value' del que se extrae el id de marca.
        value = facet.get("Id") or facet.get("Value")
        try:
            brand_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return brand_ids

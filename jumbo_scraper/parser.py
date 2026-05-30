"""Normaliza el JSON de producto de Constructor.io a una fila plana por SKU."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Iterator, List


def _category_path(product: dict) -> str:
    """Construye la ruta de categoría desde ProductCategoryIds y ProductCategories.

    ProductCategoryIds: '/20/783/22/'  →  'Frutas y Verduras > Frutas > Fruta'
    ProductCategories:  {'20': 'Frutas y Verduras', '783': 'Frutas', '22': 'Fruta'}
    """
    raw_cats = product.get("ProductCategories") or {}
    if isinstance(raw_cats, str):
        try:
            raw_cats = json.loads(raw_cats)
        except (json.JSONDecodeError, ValueError):
            raw_cats = {}

    id_path = product.get("ProductCategoryIds", "")
    ids = [x for x in id_path.strip("/").split("/") if x]
    if ids and raw_cats:
        return " > ".join(raw_cats.get(i, i) for i in ids)
    return " > ".join(raw_cats.values()) if raw_cats else ""


def _decode_json_field(product: dict, key: str) -> dict:
    """Decodifica un campo que Constructor.io entrega como lista con un JSON."""
    raw = product.get(key, "{}")
    if isinstance(raw, list):
        raw = raw[0] if raw else "{}"
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (json.JSONDecodeError, ValueError):
        return {}


def _first_image(product: dict) -> str:
    imgs = product.get("images") or []
    if isinstance(imgs, list) and imgs:
        return imgs[0]
    return product.get("image_url", "")


def _link_text(url: str) -> str:
    # URL format: https://www.jumbo.cl/{slug}/p  — strip the trailing /p
    parts = url.rstrip("/").rsplit("/", 1)
    segment = parts[-1] if parts else ""
    return parts[-2].rsplit("/", 1)[-1] if segment == "p" and len(parts) >= 2 else segment


def _seller_name(product: dict) -> str:
    seller = product.get("Vendido por") or product.get("soldBy", "")
    if isinstance(seller, list):
        return seller[0] if seller else ""
    return str(seller)


def parse_product(product: dict, scraped_at: str | None = None) -> List[Dict]:
    """Convierte un resultado de Constructor.io en una fila.

    En esta API cada result.data ya corresponde a un único SKU, por lo que
    siempre devolvemos una lista de un único elemento.
    """
    scraped_at = scraped_at or datetime.now(timezone.utc).isoformat()

    pd = _decode_json_field(product, "ProductData")

    measurement_unit = (
        pd.get("measurement_unit")
        or product.get("MeasurementUnit", "")
    )
    unit_multiplier = pd.get("unit_multiplier") or product.get("UnitMultiplier")

    row: Dict = {
        "productId":            product.get("ProductId") or product.get("productId"),
        "productName":          product.get("ProductName") or product.get("value", ""),
        "brand":                (
                                    product.get("BrandName")
                                    or (product.get("brands") or [""])[0]
                                ),
        "brandId":              product.get("BrandId"),
        "categoryPath":         _category_path(product),
        "skuId":                product.get("id"),
        "skuName":              product.get("ProductName") or product.get("value", ""),
        "ean":                  "",                     # no expuesto en el índice público
        "refId":                product.get("RefId", ""),
        "measurementUnit":      measurement_unit,
        "unitMultiplier":       unit_multiplier,
        "price":                product.get("price") or product.get("sellingPrice"),
        "listPrice":            product.get("listPrice"),
        "priceWithoutDiscount": product.get("originalPrice"),
        "available":            not product.get("outOfStock", False),
        "availableQuantity":    product.get("stockLevel"),
        "sellerId":             "",
        "sellerName":           _seller_name(product),
        "imageUrl":             _first_image(product),
        "productUrl":           product.get("url", ""),
        "linkText":             _link_text(product.get("url", "")),
        "scrapedAt":            scraped_at,
    }
    return [row]


def parse_products(products: List[dict]) -> Iterator[Dict]:
    scraped_at = datetime.now(timezone.utc).isoformat()
    for p in products:
        yield from parse_product(p, scraped_at)


# Orden de columnas para el CSV (estable y legible).
CSV_FIELDS = [
    "productId", "productName", "brand", "brandId", "categoryPath",
    "skuId", "skuName", "ean", "refId", "measurementUnit", "unitMultiplier",
    "price", "listPrice", "priceWithoutDiscount",
    "available", "availableQuantity",
    "sellerId", "sellerName", "imageUrl", "productUrl", "linkText", "scrapedAt",
]

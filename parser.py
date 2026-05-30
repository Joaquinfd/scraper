"""Normaliza el JSON de producto de VTEX a filas planas (una por SKU)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterator, List


def _category_path(product: dict) -> str:
    """VTEX entrega 'categories' como lista de rutas tipo '/Despensa/Aceites/'.
    Tomamos la más específica (la más larga)."""
    cats = product.get("categories") or []
    if not cats:
        return ""
    return max(cats, key=len).strip("/").replace("/", " > ")


def _first_image(item: dict) -> str:
    images = item.get("images") or []
    if images:
        return images[0].get("imageUrl", "")
    return ""


def parse_product(product: dict, scraped_at: str | None = None) -> List[Dict]:
    """Convierte un producto VTEX en una o varias filas (una por SKU/item).

    Cada producto puede tener múltiples 'items' (SKUs: formatos, tamaños…),
    y cada SKU múltiples 'sellers' con su oferta comercial.
    """
    scraped_at = scraped_at or datetime.now(timezone.utc).isoformat()
    rows: List[Dict] = []

    product_id = product.get("productId")
    base = {
        "productId": product_id,
        "productName": product.get("productName", ""),
        "brand": product.get("brand", ""),
        "brandId": product.get("brandId"),
        "categoryPath": _category_path(product),
        "productUrl": product.get("link", ""),
        "linkText": product.get("linkText", ""),
        "scrapedAt": scraped_at,
    }

    for item in product.get("items", []) or []:
        sellers = item.get("sellers") or []
        offer = (sellers[0].get("commertialOffer") if sellers else {}) or {}
        seller_name = sellers[0].get("sellerName", "") if sellers else ""
        seller_id = sellers[0].get("sellerId", "") if sellers else ""

        ean = item.get("ean", "")
        rows.append(
            {
                **base,
                "skuId": item.get("itemId"),
                "skuName": item.get("name", ""),
                "ean": ean,
                "refId": item.get("referenceId", [{}])[0].get("Value")
                if item.get("referenceId")
                else "",
                "measurementUnit": item.get("measurementUnit", ""),
                "unitMultiplier": item.get("unitMultiplier"),
                "price": offer.get("Price"),
                "listPrice": offer.get("ListPrice"),
                "priceWithoutDiscount": offer.get("PriceWithoutDiscount"),
                "available": offer.get("IsAvailable"),
                "availableQuantity": offer.get("AvailableQuantity"),
                "sellerId": seller_id,
                "sellerName": seller_name,
                "imageUrl": _first_image(item),
            }
        )

    # Producto sin SKUs (raro): igual dejamos una fila con los datos base.
    if not rows:
        rows.append({**base, "skuId": None, "available": None, "price": None})

    return rows


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

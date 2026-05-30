"""Spider alternativo con Scrapy (el framework de scraping más completo).

Uso:
    pip install scrapy
    scrapy runspider scrapy_alt/jumbo_spider.py -O productos.csv
    scrapy runspider scrapy_alt/jumbo_spider.py -O productos.json

Consume la MISMA API VTEX que el paquete principal, pero delega a Scrapy el
manejo de concurrencia, reintentos, autothrottle y exportación.
"""

import json

import scrapy


class JumboSpider(scrapy.Spider):
    name = "jumbo"
    allowed_domains = ["jumbo.cl"]

    BASE = "https://www.jumbo.cl"
    PAGE_SIZE = 50
    MAX_OFFSET = 2500
    SC = 1

    custom_settings = {
        # Cortesía: no abusar del servidor.
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "CONCURRENT_REQUESTS": 4,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    def start_requests(self):
        yield scrapy.Request(
            f"{self.BASE}/api/catalog_system/pub/category/tree/50",
            callback=self.parse_tree,
        )

    def parse_tree(self, response):
        tree = json.loads(response.text)
        for cat_id in self._leaf_ids(tree):
            yield self._search_request(cat_id, 0)

    def _leaf_ids(self, nodes):
        for node in nodes:
            children = node.get("children") or []
            if children:
                yield from self._leaf_ids(children)
            else:
                yield node["id"]

    def _search_request(self, category_id, offset):
        _to = min(offset + self.PAGE_SIZE - 1, self.MAX_OFFSET - 1)
        url = (
            f"{self.BASE}/api/catalog_system/pub/products/search"
            f"?fq=C:/{category_id}/&_from={offset}&_to={_to}&sc={self.SC}"
        )
        return scrapy.Request(
            url,
            callback=self.parse_products,
            cb_kwargs={"category_id": category_id, "offset": offset},
        )

    def parse_products(self, response, category_id, offset):
        products = json.loads(response.text)
        if not products:
            return

        for product in products:
            for item in product.get("items", []):
                sellers = item.get("sellers") or [{}]
                offer = sellers[0].get("commertialOffer", {}) or {}
                images = item.get("images") or [{}]
                yield {
                    "productId": product.get("productId"),
                    "productName": product.get("productName"),
                    "brand": product.get("brand"),
                    "categoryPath": (max(product.get("categories", [""]), key=len)
                                     .strip("/").replace("/", " > ")),
                    "skuId": item.get("itemId"),
                    "skuName": item.get("name"),
                    "ean": item.get("ean"),
                    "price": offer.get("Price"),
                    "listPrice": offer.get("ListPrice"),
                    "available": offer.get("IsAvailable"),
                    "availableQuantity": offer.get("AvailableQuantity"),
                    "imageUrl": images[0].get("imageUrl"),
                    "productUrl": product.get("link"),
                }

        # Página siguiente si vino llena y no superamos el tope.
        if len(products) == self.PAGE_SIZE and offset + self.PAGE_SIZE < self.MAX_OFFSET:
            yield self._search_request(category_id, offset + self.PAGE_SIZE)

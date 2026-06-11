#!/usr/bin/env python3
"""Demo del scraper v2: 100 productos de cervezas/cócteles a CSV (sin DB).

Usa el pipeline real (client, categorías, paginación, parser v2, storage);
solo filtra por categoría y corta en 100 productos.

    python demo_v2.py
"""

from __future__ import annotations

import logging

from jumbo_scraper.categories import fetch_category_tree, iter_leaf_categories
from jumbo_scraper.client import JumboClient
from jumbo_scraper.config import Config
from jumbo_scraper.parser import parse_product
from jumbo_scraper.products import iter_category_products
from jumbo_scraper.storage import Storage

TARGET_PATHS = {
    "Licores, Bebidas y Aguas > Cervezas > Cervezas Artesanales",
    "Licores, Bebidas y Aguas > Cervezas > Cervezas Destacadas",
    "Licores, Bebidas y Aguas > Cervezas > Cervezas Tradicionales",
    "Licores, Bebidas y Aguas > Cervezas > Cervezas sin Alcohol",
    "Licores, Bebidas y Aguas > Cócteles",
}
LIMIT = 100
OUTPUT_DIR = "output_demo"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("demo_v2")


def main() -> None:
    config = Config(output_dir=OUTPUT_DIR, write_jsonl=False)
    client = JumboClient(config)
    seen: set[str] = set()

    try:
        tree = fetch_category_tree(client, config)
        # Las subcategorías objetivo no son hojas del árbol de grupos de
        # Constructor.io: viven en el categoryPath de cada producto. Se
        # recorren las hojas 'Cervezas' y 'Cócteles' y se filtra por fila.
        leaves = [c for c in iter_leaf_categories(tree)
                  if "cerveza" in c.name.lower() or "cóctel" in c.name.lower()]
        logger.info("Hojas a recorrer: %s", [c.name for c in leaves])

        with Storage(OUTPUT_DIR, write_csv=True, write_jsonl=False,
                     prefix="demo_cervezas_v2") as storage:
            for cat in leaves:
                if len(seen) >= LIMIT:
                    break
                for product in iter_category_products(client, config, cat):
                    if len(seen) >= LIMIT:
                        break
                    pid = str(product.get("id"))
                    if pid in seen:
                        continue
                    rows = [r for r in parse_product(product)
                            if r.get("categoryPath") in TARGET_PATHS]
                    if not rows:
                        continue
                    seen.add(pid)
                    storage.write_rows(rows)

            logger.info("Demo lista: %d productos -> %s",
                        len(seen), storage.csv_path)
    finally:
        client.close()


if __name__ == "__main__":
    main()

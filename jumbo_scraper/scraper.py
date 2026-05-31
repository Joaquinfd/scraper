"""Orquestador: recorre categorías, pagina productos, deduplica y guarda."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from typing import List, Set

from .categories import Category, fetch_category_tree, iter_leaf_categories
from .client import JumboClient
from .config import Config
from .parser import parse_product
from .products import iter_category_products
from .storage import Storage

logger = logging.getLogger(__name__)


class JumboScraper:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.client = JumboClient(self.config)
        self.seen_product_ids: Set[str] = set()

    # ------------------------------------------------------------------ #
    def run(self) -> int:
        """Scrapea todo el catálogo. Devuelve el número de SKUs únicos procesados."""
        tree = fetch_category_tree(self.client, self.config)
        leaves: List[Category] = list(iter_leaf_categories(tree))
        logger.info("Categorías hoja a recorrer: %d", len(leaves))

        if self.config.write_db:
            from .db import DbStorage  # lazy: sqlmodel/psycopg optional for CSV-only runs
            db_cm = DbStorage(
                self.config.store_name,
                self.config.store_company,
                self.config.store_location,
                output_dir=self.config.output_dir,
            )
        else:
            db_cm = nullcontext(None)

        with Storage(
            self.config.output_dir,
            write_csv=self.config.write_csv,
            write_jsonl=self.config.write_jsonl,
        ) as file_storage, db_cm as db:
            if self.config.workers > 1:
                self._run_parallel(leaves, file_storage, db)
            else:
                self._run_sequential(leaves, file_storage, db)

            logger.info(
                "Listo. Productos únicos: %d | filas (SKUs) escritas: %d",
                len(self.seen_product_ids), file_storage.rows_written,
            )
            return len(self.seen_product_ids)

    # ------------------------------------------------------------------ #
    def _run_sequential(self, leaves: List[Category], file_storage: Storage, db) -> None:
        for i, cat in enumerate(leaves, 1):
            logger.info("[%d/%d] Categoría: %s (id=%s)", i, len(leaves), cat.name, cat.id)
            for product in iter_category_products(self.client, self.config, cat):
                self._handle_product(product, file_storage, db)

    def _run_parallel(self, leaves: List[Category], file_storage: Storage, db) -> None:
        """Paralelismo a nivel de categoría. La escritura sigue siendo en el hilo principal."""
        def collect(cat: Category):
            local_client = JumboClient(self.config)
            try:
                return list(iter_category_products(local_client, self.config, cat))
            finally:
                local_client.close()

        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = {pool.submit(collect, cat): cat for cat in leaves}
            for done, fut in enumerate(as_completed(futures), 1):
                cat = futures[fut]
                try:
                    products = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Categoría %s falló: %s", cat.id, exc)
                    continue
                logger.info("[%d/%d] %s -> %d productos",
                            done, len(leaves), cat.name, len(products))
                for product in products:
                    self._handle_product(product, file_storage, db)

    # ------------------------------------------------------------------ #
    def _handle_product(self, product: dict, file_storage: Storage, db) -> None:
        """Deduplica por skuId — cada result de Constructor.io es un SKU único."""
        pid = str(product.get("id"))
        if pid in self.seen_product_ids:
            return
        self.seen_product_ids.add(pid)
        rows = parse_product(product)
        file_storage.write_rows(rows)
        if db is not None:
            db.write_rows(rows)

    def close(self) -> None:
        self.client.close()

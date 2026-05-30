"""Configuración central del scraper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # --- Tienda ---
    base_url: str = "https://www.jumbo.cl"
    sales_channel: int = 1          # 'sc' de VTEX. jumbo.cl usa 1 por defecto.
    region_id: Optional[str] = None  # opcional: precios/stock por región (ver README)

    # --- Paginación VTEX ---
    page_size: int = 50             # máximo de items por request en la API clásica
    max_offset: int = 2500          # tope duro de _to que impone VTEX por consulta
    category_tree_depth: int = 50   # profundidad para traer todo el árbol de categorías

    # --- Red / cortesía ---
    request_timeout: float = 30.0
    min_delay: float = 0.4          # pausa mínima entre requests (segundos)
    max_delay: float = 0.9          # pausa máxima (se elige aleatoria entre min y max)
    max_retries: int = 5            # reintentos ante errores transitorios (429/5xx)
    workers: int = 1                # >1 = scraping de categorías en paralelo (con cuidado)

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # --- Salida ---
    output_dir: str = "output"
    write_csv: bool = True
    write_jsonl: bool = True

    @property
    def search_url(self) -> str:
        return f"{self.base_url}/api/catalog_system/pub/products/search"

    @property
    def category_tree_url(self) -> str:
        return f"{self.base_url}/api/catalog_system/pub/category/tree/{self.category_tree_depth}"

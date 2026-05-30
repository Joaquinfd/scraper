"""Configuración central del scraper."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    # --- Constructor.io (plataforma de búsqueda de jumbo.cl) ---
    api_key: str = "key_JopvNXKS61kwGkBe"
    section: str = "Products"

    # --- Paginación ---
    page_size: int = 50

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
    def browse_url(self) -> str:
        return "https://ac.cnstrc.com/browse/group_id"

    @property
    def groups_url(self) -> str:
        return "https://ac.cnstrc.com/browse/groups"

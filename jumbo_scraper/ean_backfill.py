"""Backfill de códigos EAN leyendo el JSON-LD de cada página de producto.

Constructor.io no indexa el código de barras, pero cada página de producto
de jumbo.cl lo expone en un bloque <script type="application/ld+json">
dentro de @graph como "gtin".

Reanudable por construcción: procesa solo productos con
    ean IS NULL AND ean_checked_at IS NULL
y marca ean_checked_at en cada intento (encontrado o no), por lo que se
puede cortar y relanzar sin repetir trabajo. Los "no encontrados" quedan
con ean NULL + ean_checked_at seteado y no se reintentan.

Uso:
    python -m jumbo_scraper.ean_backfill                 # todos los pendientes
    python -m jumbo_scraper.ean_backfill --limit 5000    # tanda acotada
    python -m jumbo_scraper.ean_backfill --workers 4
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from sqlmodel import Session, create_engine, select

from .config import Config
from .models import Product

load_dotenv()

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50          # productos por tanda (fetch paralelo + 1 commit)
_JSONLD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
_GTIN_RE = re.compile(r'"gtin(?:1[34]|8)?"\s*:\s*"(\d{8,14})"')

_thread_local = threading.local()


def _build_engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://") or (
        url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://")
    ):
        url = "postgresql+psycopg" + url[url.index("://"):]
    return create_engine(url)


def _session_for_thread(config: Config) -> requests.Session:
    """requests.Session por hilo (Session no es thread-safe)."""
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": config.user_agent,
            "Accept-Language": "es-CL,es;q=0.9",
        })
        _thread_local.session = s
    return s


def fetch_ean(config: Config, product_url: str) -> str | None:
    """Devuelve el EAN de la página de producto, o None si no está.

    Pausa aleatoria por hilo antes de cada request para repartir la carga.
    """
    time.sleep(random.uniform(config.min_delay, config.max_delay))
    session = _session_for_thread(config)
    try:
        resp = session.get(product_url, timeout=config.request_timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("Fetch falló %s: %s", product_url, exc)
        return None

    html = resp.text

    # Primero JSON-LD bien parseado; si falla, regex directo sobre el HTML.
    for block in _JSONLD_RE.findall(html):
        try:
            obj = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for item in obj.get("@graph", [obj]):
            if not isinstance(item, dict):
                continue
            gtin = (item.get("gtin") or item.get("gtin13")
                    or item.get("gtin8") or item.get("gtin14"))
            if gtin:
                return str(gtin)

    m = _GTIN_RE.search(html)
    return m.group(1) if m else None


def run_backfill(limit: int | None, workers: int, config: Config) -> tuple[int, int]:
    """Procesa productos pendientes. Devuelve (encontrados, no_encontrados)."""
    engine = _build_engine()
    found = 0
    not_found = 0
    processed = 0

    with Session(engine) as db:
        pending_total = len(db.exec(
            select(Product.sku)
            .where(Product.ean.is_(None))
            .where(Product.ean_checked_at.is_(None))
            .where(Product.product_url.is_not(None))
        ).all())
    target = min(pending_total, limit) if limit else pending_total
    logger.info("Pendientes de EAN: %d — esta corrida procesará %d (workers=%d)",
                pending_total, target, workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while processed < target:
            batch_size = min(_BATCH_SIZE, target - processed)
            with Session(engine) as db:
                batch = db.exec(
                    select(Product)
                    .where(Product.ean.is_(None))
                    .where(Product.ean_checked_at.is_(None))
                    .where(Product.product_url.is_not(None))
                    .limit(batch_size)
                ).all()

                if not batch:
                    break

                eans = list(pool.map(
                    lambda p: fetch_ean(config, p.product_url), batch
                ))

                now = datetime.now(timezone.utc)
                for product, ean in zip(batch, eans):
                    product.ean = ean
                    product.ean_checked_at = now
                    db.add(product)
                    if ean:
                        found += 1
                    else:
                        not_found += 1
                db.commit()

            processed += len(batch)
            logger.info("Progreso: %d/%d  (con EAN: %d, sin EAN: %d)",
                        processed, target, found, not_found)

    return found, not_found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill de EAN para productos jumbo.cl")
    ap.add_argument("--limit", type=int, default=None,
                    help="Máximo de productos a procesar en esta corrida (default: todos)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Fetches de páginas en paralelo (default 4)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config()
    found, not_found = run_backfill(args.limit, args.workers, config)
    print(f"\nEAN encontrados: {found}   sin EAN: {not_found}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

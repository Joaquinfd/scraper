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
_EAN_RE = re.compile(r'"ean"\s*:\s*"(\d{8,14})"')

# jumbo.cl a veces devuelve un HTML "shell" (~8 KB, sin JSON-LD) en lugar de la
# página completa (~25-68 KB). Es intermitente: al reintentar suele venir completa.
_SHELL_MAX_BYTES = 15000
_EAN_RETRIES = 3

_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_thread_local = threading.local()


def _resolve_db_url(dev: bool) -> str:
    """En --dev prefiere DEV_DATABASE_URL (cae a DATABASE_URL); si no, DATABASE_URL."""
    if dev:
        url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
    else:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DEV_DATABASE_URL o DATABASE_URL en el entorno/.env")
    return url


def _build_engine(database_url: str | None = None):
    url = database_url or os.environ["DATABASE_URL"]
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


def _extract_ean(html: str) -> str | None:
    """EAN desde el JSON-LD (@graph .gtin*) y, de fallback, por regex (gtin/ean)."""
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
    m = _GTIN_RE.search(html) or _EAN_RE.search(html)
    return m.group(1) if m else None


def fetch_ean(config: Config, product_url: str) -> str | None:
    """Devuelve el EAN de la página de producto, o None si no está.

    Reintenta cuando la página vuelve como 'shell' intermitente (HTML chico sin
    JSON-LD), que es la causa principal de EAN faltantes. Si la página es completa
    pero no trae código, no reintenta (no hay EAN que recuperar).
    Pausa aleatoria por hilo antes de cada request para repartir la carga.
    """
    session = _session_for_thread(config)
    for attempt in range(_EAN_RETRIES + 1):
        time.sleep(random.uniform(config.min_delay, config.max_delay))
        try:
            resp = session.get(product_url, timeout=config.request_timeout,
                               headers=_PAGE_HEADERS)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Fetch falló %s: %s", product_url, exc)
            if attempt < _EAN_RETRIES:
                continue
            return None

        html = resp.text
        ean = _extract_ean(html)
        if ean:
            return ean
        # Sin EAN: si parece shell, reintenta; si la página es completa, no hay EAN.
        if len(html) >= _SHELL_MAX_BYTES or attempt == _EAN_RETRIES:
            return None
    return None


def _pending_conditions(retry_missing: bool):
    """Filtros de productos a procesar.

    - normal:        ean IS NULL AND ean_checked_at IS NULL  (nunca revisados)
    - retry_missing: ean IS NULL                             (todos sin EAN, aunque
                     ya se hayan revisado — re-intenta los que fallaron antes)
    """
    conds = [Product.ean.is_(None), Product.product_url.is_not(None)]
    if not retry_missing:
        conds.append(Product.ean_checked_at.is_(None))
    return conds


def run_backfill(limit: int | None, workers: int, config: Config,
                 database_url: str | None = None,
                 retry_missing: bool = False) -> tuple[int, int]:
    """Procesa productos sin EAN. Devuelve (encontrados, no_encontrados).

    Carga la lista de SKUs pendientes UNA vez y la recorre en lotes fijos, así
    re-procesar los 'no encontrados' (retry_missing) no los re-selecciona.
    """
    engine = _build_engine(database_url)
    found = 0
    not_found = 0

    with Session(engine) as db:
        stmt = select(Product.sku).where(*_pending_conditions(retry_missing))
        if limit:
            stmt = stmt.limit(limit)
        pending_skus = list(db.exec(stmt).all())

    target = len(pending_skus)
    logger.info("Productos a procesar: %d (retry_missing=%s, workers=%d)",
                target, retry_missing, workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, target, _BATCH_SIZE):
            chunk = pending_skus[start:start + _BATCH_SIZE]
            with Session(engine) as db:
                products = db.exec(
                    select(Product).where(Product.sku.in_(chunk))
                ).all()

                urls = [p.product_url for p in products]
                eans = list(pool.map(lambda u: fetch_ean(config, u), urls))

                now = datetime.now(timezone.utc)
                for product, ean in zip(products, eans):
                    product.ean = ean
                    product.ean_checked_at = now
                    db.add(product)
                    if ean:
                        found += 1
                    else:
                        not_found += 1
                db.commit()

            logger.info("Progreso: %d/%d  (con EAN: %d, sin EAN: %d)",
                        min(start + _BATCH_SIZE, target), target, found, not_found)

    return found, not_found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill de EAN para productos jumbo.cl")
    ap.add_argument("--limit", type=int, default=None,
                    help="Máximo de productos a procesar en esta corrida (default: todos)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Fetches de páginas en paralelo (default 4)")
    ap.add_argument("--dev", action="store_true",
                    help="Usa la DB local (DEV_DATABASE_URL, o DATABASE_URL si no existe)")
    ap.add_argument("--retry-missing", action="store_true",
                    help="Re-procesa TODOS los productos con ean NULL (aunque ya se "
                         "hayan revisado), para recuperar los que fallaron antes")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    db_url = _resolve_db_url(args.dev)
    if args.dev:
        host = db_url.split("@", 1)[-1].split("/", 1)[0] if "@" in db_url else db_url
        logger.warning("Modo --dev -> backfill sobre DB local @ %s", host)

    config = Config()
    found, not_found = run_backfill(args.limit, args.workers, config,
                                    database_url=db_url, retry_missing=args.retry_missing)
    print(f"\nEAN encontrados: {found}   sin EAN: {not_found}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

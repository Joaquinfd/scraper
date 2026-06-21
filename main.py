#!/usr/bin/env python3
"""Punto de entrada CLI para el scraper de jumbo.cl.

Ejemplos:
    python main.py                          # scrapea todo, salida en ./output
    python main.py --workers 3 --out data   # 3 categorías en paralelo
    python main.py --db                     # además escribe en PostgreSQL (requiere DATABASE_URL)
    python main.py --db --no-csv --no-jsonl # solo DB, sin archivos
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from jumbo_scraper import Config, JumboScraper

# Categorías y tope para el modo --dev
DEV_CATEGORIES = ["cerveza", "despensa"]
DEV_MAX_PRODUCTS = 2000


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scraper del catálogo de jumbo.cl (Constructor.io)")
    p.add_argument("--out", default="output", help="Directorio de salida")
    p.add_argument("--workers", type=int, default=1, help="Categorías en paralelo (default 1)")
    p.add_argument("--delay-min", type=float, default=0.4, help="Pausa mínima entre requests (s)")
    p.add_argument("--delay-max", type=float, default=0.9, help="Pausa máxima entre requests (s)")
    p.add_argument("--no-csv", action="store_true", help="No escribir CSV")
    p.add_argument("--no-jsonl", action="store_true", help="No escribir JSONL")
    p.add_argument("--db", action="store_true", help="Escribir price snapshots en PostgreSQL (requiere DATABASE_URL en .env)")
    p.add_argument("--dev", action="store_true",
                   help=f"Corrida acotada a DB local: {DEV_MAX_PRODUCTS} productos de "
                        f"Despensa y Cervezas (usa DEV_DATABASE_URL, o DATABASE_URL si no existe; "
                        f"crea tablas si faltan)")
    p.add_argument("--store-name", default="Jumbo Online", help="Nombre de la tienda en DB (default: 'Jumbo Online')")
    p.add_argument("--store-location", default=None, help="Ubicación de la tienda en DB (opcional)")
    p.add_argument("--verbose", "-v", action="store_true", help="Logging detallado")
    return p


def _dev_config(args) -> Config | None:
    """Config para --dev: DB local, categorías y tope acotados.

    Usa DEV_DATABASE_URL si está; si no, cae a DATABASE_URL. Devuelve None si no
    hay ninguna (el caller corta con código de error).
    """
    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.environ.get("DEV_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        logging.error("Modo --dev: define DEV_DATABASE_URL o DATABASE_URL en .env")
        return None

    host = db_url.split("@", 1)[-1].split("/", 1)[0] if "@" in db_url else db_url
    logging.warning("Modo --dev -> escribiendo en DB local @ %s "
                    "(%d productos de %s)", host, DEV_MAX_PRODUCTS, DEV_CATEGORIES)
    if "neon.tech" in db_url:
        logging.warning("OJO: la URL apunta a Neon, no a una DB local.")

    return Config(
        workers=1,
        min_delay=args.delay_min,
        max_delay=args.delay_max,
        output_dir="output_dev",
        write_csv=False,
        write_jsonl=False,
        write_db=True,
        store_name=args.store_name,
        store_location=args.store_location,
        db_url=db_url,
        db_create_tables=True,
        category_filter=DEV_CATEGORIES,
        max_products=DEV_MAX_PRODUCTS,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dev:
        config = _dev_config(args)
        if config is None:
            return 1
    else:
        config = Config(
            workers=args.workers,
            min_delay=args.delay_min,
            max_delay=args.delay_max,
            output_dir=args.out,
            write_csv=not args.no_csv,
            write_jsonl=not args.no_jsonl,
            write_db=args.db,
            store_name=args.store_name,
            store_location=args.store_location,
        )

    scraper = JumboScraper(config)
    try:
        total = scraper.run()
    except KeyboardInterrupt:
        logging.warning("Interrumpido por el usuario. Los datos parciales quedaron guardados.")
        return 130
    finally:
        scraper.close()

    print(f"\nProductos únicos procesados: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

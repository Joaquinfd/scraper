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
import sys

from jumbo_scraper import Config, JumboScraper


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scraper del catálogo de jumbo.cl (Constructor.io)")
    p.add_argument("--out", default="output", help="Directorio de salida")
    p.add_argument("--workers", type=int, default=1, help="Categorías en paralelo (default 1)")
    p.add_argument("--delay-min", type=float, default=0.4, help="Pausa mínima entre requests (s)")
    p.add_argument("--delay-max", type=float, default=0.9, help="Pausa máxima entre requests (s)")
    p.add_argument("--no-csv", action="store_true", help="No escribir CSV")
    p.add_argument("--no-jsonl", action="store_true", help="No escribir JSONL")
    p.add_argument("--db", action="store_true", help="Escribir price snapshots en PostgreSQL (requiere DATABASE_URL en .env)")
    p.add_argument("--store-name", default="Jumbo Online", help="Nombre de la tienda en DB (default: 'Jumbo Online')")
    p.add_argument("--store-location", default=None, help="Ubicación de la tienda en DB (opcional)")
    p.add_argument("--verbose", "-v", action="store_true", help="Logging detallado")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

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

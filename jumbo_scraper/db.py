"""DB engine and DbStorage — writes product types, products, and price snapshots to PostgreSQL."""

from __future__ import annotations

import csv
import logging
import os

from dotenv import load_dotenv
from sqlmodel import Session, create_engine, select

from .models import MeasurementUnit, PriceSnapshot, Product, ProductType, Store

load_dotenv()

logger = logging.getLogger(__name__)

_UNIT_MAP: dict[str, MeasurementUnit] = {
    "kg": MeasurementUnit.KG,
    "l": MeasurementUnit.L,
    "lt": MeasurementUnit.L,
    "lts": MeasurementUnit.L,
    "ml": MeasurementUnit.ML,
    "g": MeasurementUnit.G,
    "gr": MeasurementUnit.G,
    "un": MeasurementUnit.UN,
    "unid": MeasurementUnit.UN,
    "und": MeasurementUnit.UN,
}

_ERROR_FIELDS = ["skuId", "productName", "categoryPath", "price", "error"]
_CATEGORY_FIELDS = ["category_path", "last_segment", "measurement_unit"]


def _normalize_unit(raw: str | None) -> MeasurementUnit:
    key = (raw or "").strip().lower().rstrip(".")
    return _UNIT_MAP.get(key, MeasurementUnit.UN)


def _type_name(row: dict) -> str:
    path = str(row.get("categoryPath") or "").strip()
    segments = [s.strip() for s in path.split(">")]
    name = segments[-1] if segments and segments[-1] else "Sin categoría"
    return name[:50]


def _build_engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://") or (
        url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://")
    ):
        url = "postgresql+psycopg" + url[url.index("://"):]
    return create_engine(url)


def _upsert_store(session: Session, name: str, company: str, location: str | None) -> Store:
    store = session.exec(select(Store).where(Store.name == name)).first()
    if not store:
        store = Store(name=name, company=company, location=location)
        session.add(store)
        session.commit()
        session.refresh(store)
    return store


class DbStorage:
    """Writes product types, products, and price snapshots directly to PostgreSQL.

    On exit writes two files to output_dir:
      - failed_rows.csv  — rows that could not be written and why
      - categories.csv   — all unique category paths found (use to filter food categories)
    """

    def __init__(
        self,
        store_name: str,
        store_company: str,
        store_location: str | None = None,
        output_dir: str = "output",
    ):
        self.engine = _build_engine()
        self.store_name = store_name
        self.store_company = store_company
        self.store_location = store_location
        self._output_dir = output_dir
        self._store_id: int | None = None
        self.rows_written = 0
        self.rows_skipped = 0
        self._categories: dict[str, str] = {}
        self._error_file = None
        self._error_writer = None

    def __enter__(self) -> "DbStorage":
        os.makedirs(self._output_dir, exist_ok=True)
        error_path = os.path.join(self._output_dir, "failed_rows.csv")
        self._error_file = open(error_path, "w", newline="", encoding="utf-8-sig")
        self._error_writer = csv.DictWriter(
            self._error_file, fieldnames=_ERROR_FIELDS, extrasaction="ignore"
        )
        self._error_writer.writeheader()

        with Session(self.engine) as session:
            store = _upsert_store(session, self.store_name, self.store_company, self.store_location)
            self._store_id = store.id
        logger.info("Store '%s' (id=%d) listo.", self.store_name, self._store_id)
        return self

    def write_rows(self, rows: list[dict]) -> None:
        for row in rows:
            self._write_row(row)

    def _write_row(self, row: dict) -> None:
        category_path = str(row.get("categoryPath") or "").strip()
        if category_path and category_path not in self._categories:
            self._categories[category_path] = _normalize_unit(row.get("measurementUnit")).value

        sku = str(row.get("skuId") or "")
        price_raw = row.get("price")

        if not sku or price_raw is None:
            self._log_error(row, "sin skuId o price")
            self.rows_skipped += 1
            return

        name = str(row.get("productName") or row.get("skuName") or "")[:100]
        brand = str(row.get("brand") or "")[:40]
        unit_amount = float(row.get("unitMultiplier") or 1.0) or 1.0
        type_name = _type_name(row)
        unit = _normalize_unit(row.get("measurementUnit"))

        try:
            with Session(self.engine) as session:
                pt = session.exec(
                    select(ProductType).where(ProductType.name == type_name)
                ).first()
                if not pt:
                    pt = ProductType(name=type_name, measurement_unit=unit)
                    session.add(pt)
                    session.commit()
                    session.refresh(pt)

                if session.get(Product, sku) is None:
                    session.add(Product(
                        sku=sku,
                        name=name,
                        brand=brand,
                        unit_amount=unit_amount,
                        product_type_id=pt.id,
                    ))
                    session.commit()

                session.add(PriceSnapshot(
                    price=round(float(price_raw)),
                    product_sku=sku,
                    store_id=self._store_id,
                ))
                session.commit()
                self.rows_written += 1
        except Exception as exc:
            logger.error("Error guardando SKU %s: %s", sku, exc)
            self._log_error(row, str(exc))
            self.rows_skipped += 1

    def _log_error(self, row: dict, error: str) -> None:
        if self._error_writer:
            self._error_writer.writerow({
                "skuId": row.get("skuId"),
                "productName": row.get("productName"),
                "categoryPath": row.get("categoryPath"),
                "price": row.get("price"),
                "error": error,
            })
            self._error_file.flush()

    def __exit__(self, *exc) -> None:
        cat_path = os.path.join(self._output_dir, "categories.csv")
        with open(cat_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=_CATEGORY_FIELDS)
            writer.writeheader()
            for path, unit in sorted(self._categories.items()):
                segments = [s.strip() for s in path.split(">")]
                writer.writerow({
                    "category_path": path,
                    "last_segment": segments[-1] if segments else "",
                    "measurement_unit": unit,
                })
        logger.info(
            "Categorías únicas: %d → %s", len(self._categories), cat_path
        )

        if self._error_file:
            self._error_file.close()
        logger.info(
            "DB: %d escritos, %d omitidos → %s",
            self.rows_written, self.rows_skipped,
            os.path.join(self._output_dir, "failed_rows.csv"),
        )

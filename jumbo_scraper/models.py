"""SQLModel table classes that mirror the backend schema (read/write subset)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


class MeasurementUnit(str, Enum):
    KG = "kg"
    L = "l"
    ML = "ml"
    G = "g"
    UN = "un"


class ProductType(SQLModel, table=True):
    __tablename__ = "producttype"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=50)
    measurement_unit: MeasurementUnit


class Product(SQLModel, table=True):
    __tablename__ = "product"

    sku: str = Field(max_length=50, primary_key=True)
    name: str = Field(max_length=100)
    brand: str = Field(max_length=40)
    unit_amount: float
    product_type_id: uuid.UUID = Field(foreign_key="producttype.id")
    image_url: str | None = Field(default=None)
    product_url: str | None = Field(default=None)

    # --- v2: detalle de producto (nombres = atributos Jumbo en snake_case) ---
    ean: str | None = Field(default=None, max_length=14)
    ean_checked_at: datetime | None = Field(default=None)
    # Contenido real del SKU: unidad base normalizada y total en esa unidad
    # (ej: una lata de 470 cc -> 'l' / 0.47; un pack 24x330 cc -> 'l' / 7.92)
    measurement_unit_un: str | None = Field(default=None, max_length=5)
    unit_multiplier_un: float | None = Field(default=None)
    # ref_id Jumbo: sufijo '-PAK' identifica packs
    ref_id: str | None = Field(default=None, max_length=50)
    cart_limit: int | None = Field(default=None)
    # El tipo de producto se modela vía product_type_id (FK a producttype). No se
    # persisten tipo_de_producto, category_path, id_grupo, id_subrubro, envase,
    # origen ni pais_de_origen (sin uso en la app).


class Store(SQLModel, table=True):
    __tablename__ = "store"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    company: str = Field(max_length=30)
    location: str | None = Field(default=None, max_length=150)


class PriceSnapshot(SQLModel, table=True):
    __tablename__ = "pricesnapshot"

    id: int | None = Field(default=None, primary_key=True)
    price: int
    snapshot_datetime: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    product_sku: str = Field(foreign_key="product.sku")
    store_id: int = Field(foreign_key="store.id")

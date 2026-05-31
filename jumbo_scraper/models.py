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

"""Load the store's CSV exports into typed, immutable records."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..domain.money import to_money

PRODUCT_STATUSES = {"active", "discontinued", "coming_soon"}
ORDER_STATUSES = {"pending", "confirmed", "shipped", "delivered", "cancelled"}


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    description: str


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    price: Decimal
    category_id: int
    description: str
    stock: int
    status: str
    specs: dict = field(hash=False)
    created_at: date


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class Order:
    id: int
    customer_id: int
    order_date: date
    status: str
    total: Decimal
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItem, ...]

    @property
    def installments(self) -> int:
        """``credit_6x`` -> 6; any non-credit method -> 1."""

        method, _, count = self.payment_method.partition("_")
        return int(count.rstrip("x")) if method == "credit" and count else 1


@dataclass(frozen=True)
class Promotion:
    id: int
    product_id: int
    discount_percent: Decimal
    description: str
    is_active: bool


@dataclass
class StoreData:
    categories: dict[int, Category]
    products: dict[int, Product]
    customers: dict[int, Customer]
    orders: dict[int, Order]
    promotions: list[Promotion]

    def products_in(self, category_id: int) -> list[Product]:
        return [p for p in self.products.values() if p.category_id == category_id]

    def promotions_for(self, product_id: int) -> list[Promotion]:
        return [p for p in self.promotions if p.product_id == product_id]


def _find_csv(data_dir: Path, table: str) -> Path:
    """Match ``<table>.csv`` or exported names like ``<export> - <table>.csv``."""

    matches = [
        path for path in data_dir.glob("*.csv")
        if path.stem == table or path.stem.endswith(f" - {table}")
    ]
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly one CSV for table '{table}' in {data_dir}, got {matches}")
    return matches[0]


def _rows(data_dir: Path, table: str) -> list[dict[str, str]]:
    with _find_csv(data_dir, table).open(encoding="utf-8", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def _optional(value: str) -> str | None:
    return value or None


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_store_data(data_dir: Path) -> StoreData:
    categories = {
        int(r["category_id"]): Category(int(r["category_id"]), r["name"], r["description"])
        for r in _rows(data_dir, "categories")
    }

    products = {}
    for r in _rows(data_dir, "products"):
        status = r["status"].lower()
        if status not in PRODUCT_STATUSES:
            raise ValueError(f"product {r['product_id']}: unknown status {status!r}")
        products[int(r["product_id"])] = Product(
            id=int(r["product_id"]),
            name=r["name"],
            price=to_money(r["price_brl"]),
            category_id=int(r["category_id"]),
            description=r["description"],
            stock=int(r["stock_quantity"]),
            status=status,
            specs=json.loads(r["specs"]) if r["specs"] else {},
            created_at=date.fromisoformat(r["created_at"]),
        )

    customers = {
        int(r["customer_id"]): Customer(int(r["customer_id"]), r["name"], r["phone"], r["email"].lower(), r["city"])
        for r in _rows(data_dir, "customers")
    }

    items: dict[int, list[OrderItem]] = {}
    for r in _rows(data_dir, "order_items"):
        items.setdefault(int(r["order_id"]), []).append(OrderItem(int(r["product_id"]), int(r["quantity"])))

    orders = {}
    for r in _rows(data_dir, "orders"):
        status = r["status"].lower()
        if status not in ORDER_STATUSES:
            raise ValueError(f"order {r['order_id']}: unknown status {status!r}")
        order_id = int(r["order_id"])
        orders[order_id] = Order(
            id=order_id,
            customer_id=int(r["customer_id"]),
            order_date=date.fromisoformat(r["order_date"]),
            status=status,
            total=to_money(r["total_brl"]),
            payment_method=r["payment_method"].lower(),
            tracking_code=_optional(r["tracking_code"]),
            estimated_delivery=_optional_date(r["estimated_delivery"]),
            notes=_optional(r["notes"]),
            items=tuple(items.get(order_id, [])),
        )

    promotions = [
        Promotion(
            id=int(r["promotion_id"]),
            product_id=int(r["product_id"]),
            discount_percent=Decimal(r["discount_percent"]),
            description=r["description"],
            is_active=r["is_active"] in {"1", "true", "True"},
        )
        for r in _rows(data_dir, "promotions")
    ]

    return StoreData(categories, products, customers, orders, promotions)

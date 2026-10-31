"""Data-quality report: inconsistencies the agent must handle instead of hiding.

Run with ``python -m emporio.data.quality``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..domain.money import brl
from ..domain.orders import STALE_AFTER_DAYS
from ..domain.pricing import check_installments
from .loader import StoreData

TRACKING_FORMAT = re.compile(r"^BR[A-Z0-9]{9}BR$")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "info" | "warning" | "error"
    message: str
    handling: str


def run_checks(data: StoreData, today: date) -> list[Finding]:
    findings: list[Finding] = []

    def add(code: str, severity: str, message: str, handling: str) -> None:
        findings.append(Finding(code, severity, message, handling))

    for category in data.categories.values():
        if not data.products_in(category.id):
            add("CATEGORY_EMPTY", "warning", f"category '{category.name}' has no products",
                "agent says the category has no items in the catalog right now; never invents products")

    for p in data.products.values():
        if p.status == "active" and p.stock <= 0:
            add("PRODUCT_NO_STOCK", "info", f"#{p.id} {p.name} is active with stock 0",
                "shown as temporarily unavailable, with alternatives")
        if p.status == "discontinued" and p.stock > 0:
            add("DISCONTINUED_WITH_STOCK", "warning", f"#{p.id} {p.name} is discontinued but has stock {p.stock}",
                "status wins: not offered for sale")
        if p.status == "coming_soon" and p.stock > 0:
            add("COMING_SOON_WITH_STOCK", "warning", f"#{p.id} {p.name} is coming_soon but has stock {p.stock}",
                "status wins: shown as 'em breve', not for sale")

    promo_count = Counter(promo.product_id for promo in data.promotions)
    for product_id, count in sorted(promo_count.items()):
        if product_id not in data.products:
            add("PROMO_UNKNOWN_PRODUCT", "error", f"promotion for unknown product #{product_id}", "ignored")
        elif count > 1:
            add("PROMO_MULTIPLE_ROWS", "info", f"product #{product_id} has {count} promotion rows",
                "only active rows count; promotions are not cumulative (best active one applies)")

    emails = Counter(customer.email for customer in data.customers.values())
    for email, count in emails.items():
        if count > 1:
            add("CUSTOMER_DUPLICATE_EMAIL", "warning", f"{count} customers share the e-mail {email}",
                "e-mail alone never identifies a customer; verification needs a second factor")

    for order in data.orders.values():
        if order.customer_id not in data.customers:
            add("ORDER_UNKNOWN_CUSTOMER", "error", f"order #{order.id}: unknown customer", "order cannot be verified")
        unknown = [item.product_id for item in order.items if item.product_id not in data.products]
        if unknown:
            add("ORDER_UNKNOWN_PRODUCT", "error", f"order #{order.id}: unknown products {unknown}", "shown by id")
            continue

        expected = sum((data.products[i.product_id].price * i.quantity for i in order.items), Decimal(0))
        if order.items and abs(expected - order.total) > Decimal("0.01"):
            add("ORDER_TOTAL_MISMATCH", "warning",
                f"order #{order.id}: total {brl(order.total)} but items at current list price sum {brl(expected)}",
                "agent reports the order total as recorded; price history/discounts are not in the data")

        for item in order.items:
            product = data.products[item.product_id]
            if product.status == "coming_soon" and order.status != "cancelled":
                add("ORDER_COMING_SOON_PRODUCT", "warning",
                    f"order #{order.id} ({order.status}) contains #{product.id} {product.name}, "
                    "which is still 'coming_soon'", "order data is reported as recorded")

        installment_check = check_installments(order.total, order.installments)
        if not installment_check.decision.allowed:
            add("ORDER_INSTALLMENT_RULE", "warning",
                f"order #{order.id}: {order.payment_method} breaks the installment policy "
                f"({installment_check.decision.reason})",
                "historical orders are not re-validated; new quotes follow the policy")

        if order.status in ("shipped", "delivered") and not order.tracking_code:
            add("ORDER_NO_TRACKING", "warning", f"order #{order.id} is {order.status} without tracking code",
                "agent offers to escalate")
        if order.tracking_code and not TRACKING_FORMAT.match(order.tracking_code):
            add("ORDER_TRACKING_FORMAT", "warning", f"order #{order.id}: tracking code {order.tracking_code} "
                "does not follow BR + 9 chars + BR", "shown as recorded")
        if order.status == "shipped" and order.estimated_delivery and today > order.estimated_delivery:
            add("ORDER_LATE", "info", f"order #{order.id} is late (estimated {order.estimated_delivery})",
                "agent apologises and offers a complaint ticket")
        if order.status in ("pending", "confirmed") and (today - order.order_date).days > STALE_AFTER_DAYS:
            add("ORDER_STALE", "info",
                f"order #{order.id} is '{order.status}' for {(today - order.order_date).days} days",
                "agent offers to escalate to the team")

    return findings


def main() -> None:
    from rich.console import Console
    from rich.table import Table

    from ..config import load_settings
    from .loader import load_store_data

    settings = load_settings()
    today = settings.now().date()
    findings = run_checks(load_store_data(settings.data_dir), today)

    table = Table(title=f"Data-quality report (today = {today:%Y-%m-%d})", show_lines=True)
    for column in ("code", "severity", "finding", "how the agent handles it"):
        table.add_column(column)
    for f in findings:
        table.add_row(f.code, f.severity, f.message, f.handling)
    Console().print(table)
    print(f"{len(findings)} findings")


if __name__ == "__main__":
    main()

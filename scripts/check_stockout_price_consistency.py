#!/usr/bin/env python3
"""Check stockout price consistency and optionally fix mismatched prices.

Rule:
- For each item SKU within the same warehouse, if there is no STOCKIN receipt
  between stockout records, the stockout price should remain the same.
- If a price change is found without an intervening STOCKIN, report it and
  optionally fix the differing prices to match the first stockout price in
  that segment.
"""

from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Tuple
import sys
from pathlib import Path

# Ensure project root is on sys.path so "wms" can be imported when run as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wms import app, db  # noqa: E402
from wms.models import (  # noqa: E402
    ItemSKU,
    Item,
    Receipt,
    ReceiptType,
    Transaction,
    Warehouse,
)


@dataclass
class StockoutEntry:
    transaction_id: int
    receipt_id: int
    receipt_date: str
    count: int
    price: Decimal


@dataclass
class SegmentIssue:
    item_sku_id: int
    item_name: str
    brand: str
    spec: str
    warehouse_id: int
    warehouse_name: str
    first_entry: StockoutEntry
    differing_entries: List[StockoutEntry] = field(default_factory=list)


def _format_price(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


def _load_transactions():
    return (
        db.session.query(
            Transaction,
            Receipt,
            ItemSKU,
            Item,
            Warehouse,
        )
        .join(Receipt, Receipt.id == Transaction.receipt_id)
        .join(ItemSKU, ItemSKU.id == Transaction.itemSKU_id)
        .join(Item, Item.id == ItemSKU.item_id)
        .join(Warehouse, Warehouse.id == Receipt.warehouse_id)
        .filter(Receipt.revoked.is_(False))
        .order_by(
            Transaction.itemSKU_id,
            Receipt.warehouse_id,
            Receipt.date,
            Receipt.id,
            Transaction.id,
        )
        .all()
    )


def scan_issues() -> List[SegmentIssue]:
    rows = _load_transactions()
    issues: List[SegmentIssue] = []

    current_key: Tuple[int, int] | None = None
    current_segment: SegmentIssue | None = None

    def finalize_segment():
        nonlocal current_segment
        if current_segment and current_segment.differing_entries:
            issues.append(current_segment)
        current_segment = None

    for tx, receipt, sku, item, warehouse in rows:
        key = (tx.itemSKU_id, receipt.warehouse_id)
        if current_key != key:
            finalize_segment()
            current_key = key

        # Reset segment when stock-in occurs
        if receipt.type == ReceiptType.STOCKIN:
            finalize_segment()
            continue

        # Only check stock-out receipts to match usage statistics logic
        if receipt.type != ReceiptType.STOCKOUT:
            continue

        if tx.count >= 0:
            continue

        if tx.count == 0:
            continue

        if current_segment is None:
            current_segment = SegmentIssue(
                item_sku_id=sku.id,
                item_name=item.name,
                brand=sku.brand,
                spec=sku.spec,
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                first_entry=StockoutEntry(
                    transaction_id=tx.id,
                    receipt_id=receipt.id,
                    receipt_date=str(receipt.date),
                    count=tx.count,
                    price=tx.price,
                ),
            )
            continue

        if tx.price != current_segment.first_entry.price:
            current_segment.differing_entries.append(
                StockoutEntry(
                    transaction_id=tx.id,
                    receipt_id=receipt.id,
                    receipt_date=str(receipt.date),
                    count=tx.count,
                    price=tx.price,
                )
            )

    finalize_segment()
    return issues


def _prompt_fix(issue: SegmentIssue) -> bool:
    first_price = _format_price(issue.first_entry.price)
    prompt = (
        "是否将该物品在该仓库的后续变动出库单价修正为首次出库单价？\n"
        f"物品: {issue.item_name} / {issue.brand} / {issue.spec}\n"
        f"仓库: {issue.warehouse_name}\n"
        f"首次出库: 价格 {first_price} (receipt_id={issue.first_entry.receipt_id})\n"
        f"变动次数: {len(issue.differing_entries)}\n"
        "输入 y 确认，其它键跳过: "
    )
    return input(prompt).strip().lower() == "y"


def fix_issue(issue: SegmentIssue) -> int:
    updated = 0
    for entry in issue.differing_entries:
        tx = db.session.get(Transaction, entry.transaction_id)
        if not tx:
            continue
        receipt = db.session.get(Receipt, entry.receipt_id)
        if not receipt or receipt.revoked:
            continue
        tx.price = issue.first_entry.price
        updated += 1
    return updated


def main():
    with app.app_context():
        issues = scan_issues()
        if not issues:
            print("未发现出库单价在无入库间隔情况下变动的问题。")
            return

        print(f"发现 {len(issues)} 处出库单价变动问题。")
        total_updates = 0

        for issue in issues:
            print("\n------------------------------")
            print(f"物品: {issue.item_name} / {issue.brand} / {issue.spec}")
            print(f"仓库: {issue.warehouse_name}")
            print(
                f"首次出库价格: {_format_price(issue.first_entry.price)} "
                f"(receipt_id={issue.first_entry.receipt_id}, tx_id={issue.first_entry.transaction_id}, "
                f"date={issue.first_entry.receipt_date})"
            )
            for entry in issue.differing_entries:
                print(
                    f"- 变动出库: 价格 {_format_price(entry.price)} "
                    f"(receipt_id={entry.receipt_id}, tx_id={entry.transaction_id}, "
                    f"date={entry.receipt_date})"
                )

            if _prompt_fix(issue):
                updated = fix_issue(issue)
                total_updates += updated
                if updated:
                    print(f"已修正 {updated} 条出库记录。")
                else:
                    print("未修正任何记录。")
            else:
                print("已跳过修正。")

        if total_updates:
            db.session.commit()
            print(f"\n修正完成，共更新 {total_updates} 条出库记录。")
        else:
            print("\n未执行任何修正。")


if __name__ == "__main__":
    main()

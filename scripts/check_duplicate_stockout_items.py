#!/usr/bin/env python3
"""Scan stockout receipts for duplicate item SKU entries and optionally fix them.

For each stockout receipt, if the same SKU appears multiple times, the script
reports the entries and asks which SKU the later entry should be, then updates
transactions and warehouse inventory accordingly.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
import sys
from typing import Dict, List, Tuple

# Ensure project root is on sys.path so "wms" can be imported when run as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wms import app, db  # noqa: E402
from wms.models import (  # noqa: E402
    Item,
    ItemSKU,
    Receipt,
    ReceiptType,
    Transaction,
    Warehouse,
    WarehouseItemSKU,
)


@dataclass
class TxEntry:
    tx_id: int
    item_sku_id: int
    item_name: str
    brand: str
    spec: str
    count: int
    price: Decimal


@dataclass
class DuplicateIssue:
    receipt_id: int
    receipt_date: str
    warehouse_id: int
    warehouse_name: str
    refcode: str | None
    entries: List[TxEntry] = field(default_factory=list)


def _format_price(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


def scan_duplicates() -> List[DuplicateIssue]:
    rows = (
        db.session.query(Transaction, Receipt, ItemSKU, Item, Warehouse)
        .join(Receipt, Receipt.id == Transaction.receipt_id)
        .join(ItemSKU, ItemSKU.id == Transaction.itemSKU_id)
        .join(Item, Item.id == ItemSKU.item_id)
        .join(Warehouse, Warehouse.id == Receipt.warehouse_id)
        .filter(Receipt.revoked.is_(False))
        .filter(Receipt.type == ReceiptType.STOCKOUT)
        .filter(Transaction.count < 0)
        .order_by(Receipt.id, Transaction.id)
        .all()
    )

    grouped: Dict[
        int, Dict[int, List[Tuple[Transaction, Receipt, ItemSKU, Item, Warehouse]]]
    ] = {}
    for tx, receipt, sku, item, warehouse in rows:
        grouped.setdefault(receipt.id, {}).setdefault(sku.id, []).append(
            (tx, receipt, sku, item, warehouse)
        )

    issues: List[DuplicateIssue] = []
    for receipt_id, sku_map in grouped.items():
        for sku_id, entries in sku_map.items():
            if len(entries) < 2:
                continue
            tx, receipt, sku, item, warehouse = entries[0]
            issue = DuplicateIssue(
                receipt_id=receipt.id,
                receipt_date=str(receipt.date),
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                refcode=receipt.refcode,
            )
            for tx, receipt, sku, item, warehouse in entries:
                issue.entries.append(
                    TxEntry(
                        tx_id=tx.id,
                        item_sku_id=sku.id,
                        item_name=item.name,
                        brand=sku.brand,
                        spec=sku.spec,
                        count=tx.count,
                        price=tx.price,
                    )
                )
            issues.append(issue)

    return issues


def _get_sku(sku_id: int) -> ItemSKU | None:
    return db.session.get(ItemSKU, sku_id)


def _get_or_create_wis(warehouse_id: int, item_sku_id: int) -> WarehouseItemSKU:
    wis = (
        db.session.query(WarehouseItemSKU)
        .filter(
            WarehouseItemSKU.warehouse_id == warehouse_id,
            WarehouseItemSKU.itemSKU_id == item_sku_id,
        )
        .first()
    )
    if not wis:
        wis = WarehouseItemSKU(
            warehouse_id=warehouse_id,
            itemSKU_id=item_sku_id,
            count=0,
            average_price=0,
        )
        db.session.add(wis)
    return wis


def _adjust_inventory(
    warehouse_id: int, old_sku_id: int, new_sku_id: int, count: int
) -> None:
    if old_sku_id == new_sku_id:
        return

    old_wis = _get_or_create_wis(warehouse_id, old_sku_id)
    new_wis = _get_or_create_wis(warehouse_id, new_sku_id)

    old_before = old_wis.count
    new_before = new_wis.count

    # Remove original stockout impact for old SKU, apply to new SKU
    old_wis.count = old_wis.count - count
    new_wis.count = new_wis.count + count

    delta = -count
    print(
        "库存已同步调整: "
        f"旧SKU {old_sku_id} {old_before} -> {old_wis.count} (+{delta}), "
        f"新SKU {new_sku_id} {new_before} -> {new_wis.count} (-{delta})"
    )


def _prompt_new_sku(entry: TxEntry) -> int | None:
    prompt = f"请输入 tx_id={entry.tx_id} 的正确 SKU ID（回车跳过）: "
    while True:
        value = input(prompt).strip()
        if value == "":
            return None
        if not value.isdigit():
            print("请输入有效的数字 SKU ID。")
            continue
        sku_id = int(value)
        sku = _get_sku(sku_id)
        if not sku:
            print("SKU 不存在，请重新输入。")
            continue
        return sku_id


def _set_transaction_sku(tx: Transaction, receipt: Receipt, new_sku_id: int) -> None:
    old_sku_id = tx.itemSKU_id
    if old_sku_id == new_sku_id:
        return

    _adjust_inventory(receipt.warehouse_id, old_sku_id, new_sku_id, tx.count)

    new_wis = (
        db.session.query(WarehouseItemSKU)
        .filter(
            WarehouseItemSKU.warehouse_id == receipt.warehouse_id,
            WarehouseItemSKU.itemSKU_id == new_sku_id,
        )
        .first()
    )
    new_price = Decimal("0")
    if new_wis and new_wis.average_price:
        new_price = Decimal(str(new_wis.average_price))

    tx.itemSKU_id = new_sku_id
    tx.price = new_price


def main():
    with app.app_context():
        issues = scan_duplicates()
        if not issues:
            print("未发现同一出库单内重复物品的情况。")
            return

        print(f"发现 {len(issues)} 张出库单存在重复物品。")
        total_updates = 0

        for issue in issues:
            print("\n------------------------------")
            print(
                f"出库单: receipt_id={issue.receipt_id}, refcode={issue.refcode}, "
                f"date={issue.receipt_date}, warehouse={issue.warehouse_name}"
            )

            for idx, entry in enumerate(issue.entries, start=1):
                print(
                    f"[{idx}] SKU={entry.item_sku_id} {entry.item_name} / {entry.brand} / {entry.spec} "
                    f"count={entry.count} price={_format_price(entry.price)} tx_id={entry.tx_id}"
                )

            # Ask user for fixes starting from the second entry
            for entry in issue.entries[1:]:
                sku_id = _prompt_new_sku(entry)
                if not sku_id:
                    continue

                sku = _get_sku(sku_id)
                if not sku:
                    continue

                item = db.session.get(Item, sku.item_id)
                print(
                    f"将 tx_id={entry.tx_id} 改为 SKU={sku.id} {item.name} / {sku.brand} / {sku.spec}"
                )

                tx = db.session.get(Transaction, entry.tx_id)
                receipt = db.session.get(Receipt, issue.receipt_id)
                if not tx or not receipt or receipt.revoked:
                    print("记录不存在，已跳过。")
                    continue

                _set_transaction_sku(tx, receipt, sku_id)
                total_updates += 1

        if total_updates:
            db.session.commit()
            print(f"\n修正完成，共更新 {total_updates} 条出库记录，并已更新库存。")
        else:
            print("\n未执行任何修正。")


if __name__ == "__main__":
    main()

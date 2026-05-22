#!/usr/bin/env python3
"""Repair dirty tool-inventory ownership data.

What this script fixes
- Rebuilds ToolInventory counts from each user's owned warehouse stock.
- Moves tool-inventory rows that are clearly attached to the wrong user.
- Reports ambiguous cases where the ownership cannot be inferred safely.

Safety model
- Dry-run by default.
- Use --apply to write changes.
- Use --purge-orphans to delete tool-inventory rows that cannot be mapped to any
  unique owned warehouse and are not present in the current warehouse stock map.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from wms import app, db  # noqa: E402
from wms.models import ItemSKU, ToolInventory, Warehouse, WarehouseItemSKU  # noqa: E402


@dataclass(frozen=True)
class WarehouseStock:
    owner_id: int
    warehouse_id: int
    sku_id: int
    count: int


@dataclass(frozen=True)
class MovePlan:
    source_user_id: int
    target_user_id: int
    sku_id: int
    source_count: int
    warehouse_count: int
    pending_scrap: int


def _build_owner_warehouse_map() -> dict[int, Warehouse]:
    """Return owners that have exactly one non-public warehouse."""
    warehouses = (
        db.session.query(Warehouse)
        .filter(Warehouse.owner_id.isnot(None), Warehouse.is_public.is_(False))
        .order_by(Warehouse.owner_id.asc(), Warehouse.id.asc())
        .all()
    )
    grouped: dict[int, list[Warehouse]] = defaultdict(list)
    for warehouse in warehouses:
        grouped[warehouse.owner_id].append(warehouse)

    return {
        owner_id: owned_warehouses[0]
        for owner_id, owned_warehouses in grouped.items()
        if len(owned_warehouses) == 1
    }


def _build_stock_map(
    owner_warehouses: dict[int, Warehouse],
) -> dict[int, WarehouseStock]:
    """Return the authoritative stock row for each tool SKU when ownership is unique."""
    stock_map: dict[int, WarehouseStock] = {}
    for owner_id, warehouse in owner_warehouses.items():
        rows = (
            db.session.query(WarehouseItemSKU)
            .join(ItemSKU)
            .join(ItemSKU.item)
            .filter(
                WarehouseItemSKU.warehouse_id == warehouse.id,
                ItemSKU.disabled.is_(False),
                ItemSKU.item.has(is_tool=True),
            )
            .all()
        )
        for row in rows:
            stock = WarehouseStock(
                owner_id=owner_id,
                warehouse_id=warehouse.id,
                sku_id=row.itemSKU_id,
                count=row.count,
            )
            existing = stock_map.get(row.itemSKU_id)
            if existing is None:
                stock_map[row.itemSKU_id] = stock
            else:
                # Ambiguous: the same SKU exists in more than one uniquely-owned warehouse.
                # Leave it for manual review.
                stock_map[row.itemSKU_id] = WarehouseStock(
                    owner_id=-1,
                    warehouse_id=-1,
                    sku_id=row.itemSKU_id,
                    count=-1,
                )
    return stock_map


def _describe_warehouse(warehouse: Warehouse | None) -> str:
    if not warehouse:
        return "<none>"
    return f"{warehouse.name}(id={warehouse.id}, owner_id={warehouse.owner_id})"


def _describe_sku(sku_id: int) -> str:
    sku = (
        db.session.query(ItemSKU)
        .join(ItemSKU.item)
        .filter(ItemSKU.id == sku_id)
        .first()
    )
    if not sku:
        return f"SKU(id={sku_id})"
    item_name = sku.item.name if sku.item else "<unknown item>"
    return f"SKU(id={sku.id}, item={item_name}, brand={sku.brand}, spec={sku.spec})"


def _print_detailed_plan(
    updates: list[tuple[int, int, int]],
    moves: list[MovePlan],
    purges: list[tuple[int, int]],
    timestamp: str,
) -> None:
    """Print human-readable repair items with serial number, content, and time."""

    if not updates and not moves and not purges:
        print("No row-level repairs required.")
        return

    for user_id, sku_id, count in updates:
        print(
            f"更新 | 内容: {_describe_sku(sku_id)}, user_id={user_id}, count -> {count} | 时间: {timestamp}"
        )

    for move in moves:
        print(
            f"迁移 | 内容: {_describe_sku(move.sku_id)}, from user_id={move.source_user_id} "
            + f"to user_id={move.target_user_id}, tool_count -> {move.source_count}, "
            + f"warehouse_count -> {move.warehouse_count}, pending_scrap -> {move.pending_scrap} | {timestamp}"
        )

    for user_id, sku_id in purges:
        print(
            f"删除 | 内容: {_describe_sku(sku_id)}, user_id={user_id} | 时间: {timestamp}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the database instead of only printing the plan.",
    )
    parser.add_argument(
        "--purge-orphans",
        action="store_true",
        help="Delete tool-inventory rows that cannot be mapped to any unique owned warehouse.",
    )
    args = parser.parse_args()

    with app.app_context():
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        owner_warehouses = _build_owner_warehouse_map()
        stock_map = _build_stock_map(owner_warehouses)

        duplicate_owners = (
            db.session.query(Warehouse.owner_id, db.func.count(Warehouse.id))
            .filter(Warehouse.owner_id.isnot(None), Warehouse.is_public.is_(False))
            .group_by(Warehouse.owner_id)
            .having(db.func.count(Warehouse.id) > 1)
            .all()
        )

        if duplicate_owners:
            print("Duplicate warehouse owners found:")
            for owner_id, warehouse_count in duplicate_owners:
                print(f"  owner_id={owner_id} has {warehouse_count} warehouses")
        else:
            print("No duplicate warehouse owners found.")

        # Build the repair plan.
        moves: list[MovePlan] = []
        updates: list[tuple[int, int, int]] = []  # (user_id, sku_id, count)
        purges: list[tuple[int, int]] = []  # (user_id, sku_id)
        moved_skus: set[int] = set()

        all_tool_rows = db.session.query(ToolInventory).all()
        for row in all_tool_rows:
            stock = stock_map.get(row.itemSKU_id)
            if stock is None:
                # SKU is not present in any uniquely-owned warehouse.
                if args.purge_orphans:
                    purges.append((row.user_id, row.itemSKU_id))
                continue
            if stock.owner_id == -1:
                # Ambiguous ownership for this SKU; manual review required.
                continue
            if row.user_id != stock.owner_id:
                moves.append(
                    MovePlan(
                        source_user_id=row.user_id,
                        target_user_id=stock.owner_id,
                        sku_id=row.itemSKU_id,
                        source_count=row.count,
                        warehouse_count=stock.count,
                        pending_scrap=row.pending_scrap,
                    )
                )
                moved_skus.add(row.itemSKU_id)
            else:
                if row.count != stock.count:
                    updates.append((row.user_id, row.itemSKU_id, stock.count))

        # Also ensure canonical rows exist even if a wrong row did not.
        for sku_id, stock in stock_map.items():
            if stock.owner_id <= 0:
                continue
            if sku_id in moved_skus:
                continue
            row = ToolInventory.query.filter_by(
                user_id=stock.owner_id, itemSKU_id=sku_id
            ).first()
            if row is None:
                updates.append((stock.owner_id, sku_id, stock.count))
            elif row.count != stock.count:
                updates.append((stock.owner_id, sku_id, stock.count))

        print(f"Planned updates: {len(updates)}")
        print(f"Planned moves: {len(moves)}")
        print(f"Planned purges: {len(purges)}")
        _print_detailed_plan(updates, moves, purges, report_time)

        if not args.apply:
            print("Dry-run only. Re-run with --apply to write changes.")
            return 0

        # Apply updates to canonical rows.
        for user_id, sku_id, count in updates:
            row = ToolInventory.query.filter_by(
                user_id=user_id, itemSKU_id=sku_id
            ).first()
            if row is None:
                db.session.add(
                    ToolInventory(
                        user_id=user_id,
                        itemSKU_id=sku_id,
                        count=count,
                        pending_scrap=0,
                    )
                )
            else:
                row.count = count

        # Reassign clearly wrong rows to the authoritative owner.
        for move in moves:
            source_row = ToolInventory.query.filter_by(
                user_id=move.source_user_id, itemSKU_id=move.sku_id
            ).first()
            if source_row is None:
                continue
            target_row = ToolInventory.query.filter_by(
                user_id=move.target_user_id, itemSKU_id=move.sku_id
            ).first()
            if target_row is None:
                target_row = ToolInventory(
                    user_id=move.target_user_id,
                    itemSKU_id=move.sku_id,
                    count=move.source_count,
                    pending_scrap=move.pending_scrap,
                )
                db.session.add(target_row)
            else:
                target_row.count += move.source_count
                target_row.pending_scrap += move.pending_scrap
            db.session.delete(source_row)

        # Remove orphan rows if requested.
        if args.purge_orphans:
            for user_id, sku_id in purges:
                row = ToolInventory.query.filter_by(
                    user_id=user_id, itemSKU_id=sku_id
                ).first()
                if row is not None:
                    db.session.delete(row)

        db.session.commit()
        print("Repair completed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

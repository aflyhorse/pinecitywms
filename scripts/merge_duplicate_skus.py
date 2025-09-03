#!/usr/bin/env python3
"""
Script to merge duplicate ItemSKU records and update all foreign key references.

Business Logic:
- Only one SKU per (item_id, brand, spec) combination should exist
- If one is disabled and one is enabled: merge enabled into disabled, then enable the disabled
- If both are disabled: merge newer (higher id) into older (lower id)
- If both are enabled: merge newer (higher id) into older (lower id)

Updates:
- Merges WarehouseItemSKU inventory counts (sum counts, average prices weighted by count)
- Updates all Transaction references to point to the kept SKU
- Deletes duplicate SKU records
- Adds unique constraint to prevent future duplicates
"""

import sqlite3
import argparse
from typing import List, Tuple


def get_duplicates(cursor) -> List[Tuple]:
    """Get all duplicate SKU groups."""
    cursor.execute(
        """
    SELECT item_id, brand, spec, COUNT(*) as count
    FROM item_sku
    GROUP BY item_id, brand, spec
    HAVING COUNT(*) > 1
    ORDER BY count DESC, item_id, brand, spec;
    """
    )
    return cursor.fetchall()


def get_duplicate_details(cursor, item_id: int, brand: str, spec: str) -> List[Tuple]:
    """Get detailed information for a specific duplicate group."""
    cursor.execute(
        """
    SELECT id, disabled
    FROM item_sku
    WHERE item_id = ? AND brand = ? AND spec = ?
    ORDER BY id;
    """,
        (item_id, brand, spec),
    )
    return cursor.fetchall()


def determine_sku_to_keep(skus: List[Tuple]) -> Tuple[int, List[int]]:
    """
    Determine which SKU to keep and which ones to merge.

    Args:
        skus: List of (id, disabled) tuples

    Returns:
        Tuple of (keep_id, [merge_ids])
    """
    enabled_skus = [(id, disabled) for id, disabled in skus if not disabled]
    disabled_skus = [(id, disabled) for id, disabled in skus if disabled]

    if enabled_skus and disabled_skus:
        # If one is disabled and one is enabled: merge enabled into disabled, then enable the disabled
        keep_id = disabled_skus[0][0]  # Keep the disabled one (will be enabled later)
        merge_ids = [id for id, _ in enabled_skus]
        return keep_id, merge_ids
    elif not enabled_skus and disabled_skus:
        # If both are disabled: merge newer (higher id) into older (lower id)
        keep_id = min(skus, key=lambda x: x[0])[0]  # Keep oldest (lowest id)
        merge_ids = [id for id, _ in skus if id != keep_id]
        return keep_id, merge_ids
    else:
        # If both are enabled: merge newer (higher id) into older (lower id)
        keep_id = min(skus, key=lambda x: x[0])[0]  # Keep oldest (lowest id)
        merge_ids = [id for id, _ in skus if id != keep_id]
        return keep_id, merge_ids


def get_warehouse_inventory(cursor, sku_id: int) -> List[Tuple]:
    """Get warehouse inventory for a specific SKU."""
    cursor.execute(
        """
    SELECT warehouse_id, count, average_price
    FROM warehouse_item_sku
    WHERE itemSKU_id = ?;
    """,
        (sku_id,),
    )
    return cursor.fetchall()


def merge_warehouse_inventory(
    cursor, keep_id: int, merge_ids: List[int], dry_run: bool = True
):
    """Merge warehouse inventory from merge_ids into keep_id."""
    changes = []

    for merge_id in merge_ids:
        # Get inventory for the SKU being merged
        merge_inventory = get_warehouse_inventory(cursor, merge_id)

        for warehouse_id, merge_count, merge_price in merge_inventory:
            # Check if keep_id already has inventory in this warehouse
            cursor.execute(
                """
            SELECT count, average_price
            FROM warehouse_item_sku
            WHERE itemSKU_id = ? AND warehouse_id = ?;
            """,
                (keep_id, warehouse_id),
            )

            existing = cursor.fetchone()

            if existing:
                # Merge counts and calculate weighted average price
                keep_count, keep_price = existing
                new_count = keep_count + merge_count

                if new_count > 0:
                    if merge_price == 0:
                        new_price = keep_price
                    else:
                        # Weighted average: (count1 * price1 + count2 * price2) / (count1 + count2)
                        new_price = (
                            keep_count * keep_price + merge_count * merge_price
                        ) / new_count
                else:
                    new_price = 0

                changes.append(
                    f"Warehouse {warehouse_id}: Update inventory for SKU {keep_id}: "
                    f"count {keep_count} + {merge_count} = {new_count}, "
                    f"avg_price {keep_price:.2f} -> {new_price:.2f}"
                )

                if not dry_run:
                    cursor.execute(
                        """
                    UPDATE warehouse_item_sku
                    SET count = ?, average_price = ?
                    WHERE itemSKU_id = ? AND warehouse_id = ?;
                    """,
                        (new_count, new_price, keep_id, warehouse_id),
                    )
            else:
                # Create new inventory entry for keep_id
                changes.append(
                    f"Warehouse {warehouse_id}: Create new inventory for SKU {keep_id}: "
                    f"count {merge_count}, avg_price {merge_price:.2f}"
                )

                if not dry_run:
                    cursor.execute(
                        """
                    INSERT INTO warehouse_item_sku (itemSKU_id, warehouse_id, count, average_price)
                    VALUES (?, ?, ?, ?);
                    """,
                        (keep_id, warehouse_id, merge_count, merge_price),
                    )

            # Delete the old inventory entry
            changes.append(
                f"Warehouse {warehouse_id}: Delete inventory for SKU {merge_id}"
            )

            if not dry_run:
                cursor.execute(
                    """
                DELETE FROM warehouse_item_sku
                WHERE itemSKU_id = ? AND warehouse_id = ?;
                """,
                    (merge_id, warehouse_id),
                )

    return changes


def update_transaction_references(
    cursor, keep_id: int, merge_ids: List[int], dry_run: bool = True
):
    """Update all transaction references from merge_ids to keep_id."""
    changes = []

    for merge_id in merge_ids:
        # Count transactions to be updated
        cursor.execute(
            'SELECT COUNT(*) FROM "transaction" WHERE itemSKU_id = ?;', (merge_id,)
        )
        transaction_count = cursor.fetchone()[0]

        if transaction_count > 0:
            changes.append(
                f"Update {transaction_count} transactions from SKU {merge_id} to SKU {keep_id}"
            )

            if not dry_run:
                cursor.execute(
                    """
                UPDATE "transaction"
                SET itemSKU_id = ?
                WHERE itemSKU_id = ?;
                """,
                    (keep_id, merge_id),
                )

    return changes


def enable_sku_if_needed(
    cursor, keep_id: int, original_skus: List[Tuple], dry_run: bool = True
):
    """Enable the kept SKU if it was disabled but we merged enabled SKUs into it."""
    enabled_skus = [id for id, disabled in original_skus if not disabled]

    # Check if the kept SKU is disabled and we have enabled SKUs being merged
    cursor.execute("SELECT disabled FROM item_sku WHERE id = ?;", (keep_id,))
    keep_disabled = cursor.fetchone()[0]

    changes = []
    if keep_disabled and enabled_skus:
        changes.append(
            f"Enable SKU {keep_id} (was disabled, but merging enabled SKUs into it)"
        )

        if not dry_run:
            cursor.execute("UPDATE item_sku SET disabled = 0 WHERE id = ?;", (keep_id,))

    return changes


def delete_merged_skus(cursor, merge_ids: List[int], dry_run: bool = True):
    """Delete the merged SKU records."""
    changes = []

    for merge_id in merge_ids:
        changes.append(f"Delete SKU {merge_id}")

        if not dry_run:
            cursor.execute("DELETE FROM item_sku WHERE id = ?;", (merge_id,))

    return changes


def add_unique_constraint(cursor, dry_run: bool = True):
    """Add unique constraint to prevent future duplicates."""
    changes = []

    # Check if constraint already exists
    cursor.execute("PRAGMA index_list(item_sku);")
    indexes = cursor.fetchall()

    constraint_exists = False
    for index in indexes:
        cursor.execute(f"PRAGMA index_info({index[1]});")
        columns = [col[2] for col in cursor.fetchall()]
        if set(columns) == {"item_id", "brand", "spec"}:
            constraint_exists = True
            break

    if not constraint_exists:
        changes.append("Add unique constraint on (item_id, brand, spec)")

        if not dry_run:
            cursor.execute(
                """
            CREATE UNIQUE INDEX idx_item_sku_unique
            ON item_sku(item_id, brand, spec);
            """
            )
    else:
        changes.append("Unique constraint already exists")

    return changes


def main():
    parser = argparse.ArgumentParser(description="Merge duplicate ItemSKU records")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be done without making changes (default)",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Actually execute the changes"
    )
    parser.add_argument(
        "--db-path",
        default="data.db",
        help="Path to the database file (default: data.db)",
    )

    args = parser.parse_args()

    # If --execute is specified, turn off dry-run
    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN MODE ===")
        print("Use --execute to actually make changes\n")
    else:
        print("=== EXECUTING CHANGES ===")
        response = input("Are you sure you want to modify the database? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
        print()

    # Connect to database
    conn = sqlite3.connect(args.db_path)
    cursor = conn.cursor()

    # Enable foreign key checks
    cursor.execute("PRAGMA foreign_keys = ON;")

    try:
        # Get all duplicate groups
        duplicates = get_duplicates(cursor)

        if not duplicates:
            print("No duplicate SKUs found!")
            return

        print(f"Found {len(duplicates)} duplicate SKU groups:")
        total_changes = []

        for item_id, brand, spec, count in duplicates:
            print(
                f"\n--- Processing: item_id={item_id}, brand='{brand}', spec='{spec}' ({count} duplicates) ---"
            )

            # Get detailed info for this group
            skus = get_duplicate_details(cursor, item_id, brand, spec)
            print(
                f"SKUs: {[(id, 'disabled' if disabled else 'enabled') for id, disabled in skus]}"
            )

            # Determine which SKU to keep
            keep_id, merge_ids = determine_sku_to_keep(skus)
            print(f"Keep SKU {keep_id}, merge SKUs {merge_ids}")

            # Process the merge
            group_changes = []

            # 1. Merge warehouse inventory
            inventory_changes = merge_warehouse_inventory(
                cursor, keep_id, merge_ids, dry_run
            )
            group_changes.extend(inventory_changes)

            # 2. Update transaction references
            transaction_changes = update_transaction_references(
                cursor, keep_id, merge_ids, dry_run
            )
            group_changes.extend(transaction_changes)

            # 3. Enable SKU if needed
            enable_changes = enable_sku_if_needed(cursor, keep_id, skus, dry_run)
            group_changes.extend(enable_changes)

            # 4. Delete merged SKUs
            delete_changes = delete_merged_skus(cursor, merge_ids, dry_run)
            group_changes.extend(delete_changes)

            # Print changes for this group
            for change in group_changes:
                print(f"  {change}")

            total_changes.extend(group_changes)

        # Add unique constraint
        print("\n--- Adding Unique Constraint ---")
        constraint_changes = add_unique_constraint(cursor, dry_run)
        for change in constraint_changes:
            print(f"  {change}")
        total_changes.extend(constraint_changes)

        # Summary
        print("\n=== SUMMARY ===")
        print(f"Total changes: {len(total_changes)}")
        print(f"Duplicate groups processed: {len(duplicates)}")

        if not dry_run:
            conn.commit()
            print("Changes committed to database.")

            # Verify no duplicates remain
            remaining_duplicates = get_duplicates(cursor)
            if remaining_duplicates:
                print(
                    f"WARNING: {len(remaining_duplicates)} duplicate groups still exist!"
                )
            else:
                print("SUCCESS: No duplicate SKUs remaining.")
        else:
            print("No changes made (dry-run mode).")

    except Exception as e:
        if not dry_run:
            conn.rollback()
            print(f"ERROR: {e}")
            print("Changes rolled back.")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

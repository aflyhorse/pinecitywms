#!/usr/bin/env python3
"""
Fix item codes (item_sku.id) from stockin detail Excel files, and clean dirty brands.

Background: during batch upload the item code column was not recognized, so the
system auto-assigned 2026xxxx-style ids; blank brands were also stored as the
string "nan". This script matches SKUs by (item name, brand, spec), restores the
correct ids from the Excel files, and rewrites blank/nan brands to "无".

Code cleaning rule: strip all non-digit characters (e.g. "1002.1011" -> 10021011,
10020027.0 -> 10020027).

Safety:
- dry-run by default; --execute applies changes (backs up the DB file first)
- rows are skipped and reported when the target id is duplicated in the Excel
  files, has no unique match in the DB, or is already taken by another SKU
- two-phase rename (to temporary negative ids, then to targets) avoids PK clashes
- all FK tables referencing item_sku.id are updated; foreign_key_check runs after commit

Usage:
    python scripts/fix_sku_ids_from_excel.py 客房一次性用品入库明细.xlsx 制服入库明细.xlsx
    python scripts/fix_sku_ids_from_excel.py --execute --db-path data.db *.xlsx
"""

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

# All FK references to item_sku.id: (table, column)
FK_REFERENCES = [
    ("transaction", "itemSKU_id"),
    ("warehouse_item_sku", "itemSKU_id"),
    ("tool_inventory", "itemSKU_id"),
    ("employee_tool_holding", "itemSKU_id"),
    ("tool_transaction", "itemSKU_id"),
]

DEFAULT_BRAND = "无"
DEFAULT_SPEC = "通用"
# Historical batch imports stored blank cells as the string "nan"/"None"
_EMPTY_VALUES = {"", "nan", "none"}

# SQL predicate for dirty brand cleanup (blank/nan -> "无")
_DIRTY_BRAND_WHERE = "TRIM(brand) = '' OR LOWER(TRIM(brand)) IN ('nan', 'none')"


def normalize_code(value):
    """Extract the digits of an item code, dropping non-digit chars (e.g. ".")."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def normalize_brand(value):
    """Blank brand defaults to "无"."""
    if value is None:
        return DEFAULT_BRAND
    s = str(value).strip()
    return DEFAULT_BRAND if s.lower() in _EMPTY_VALUES else s


def normalize_spec(value):
    """Blank spec defaults to "通用"."""
    if value is None:
        return DEFAULT_SPEC
    s = str(value).strip()
    return DEFAULT_SPEC if s.lower() in _EMPTY_VALUES else s


def read_excel_rows(paths):
    """Read Excel files, return [(file, line_no, target_id, name, brand, spec)].

    The first column is the item code; the header row is skipped.
    """
    rows = []
    for path in paths:
        ws = openpyxl.load_workbook(path, read_only=True).active
        for line_no, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if all(c is None for c in row):
                continue
            code, name, brand, spec = row[0], row[1], row[2], row[3]
            if line_no == 1 and normalize_code(code) is None:
                continue  # header row
            if name is None:
                print(f"  [跳过] {Path(path).name} 第{line_no}行: 物品名称为空")
                continue
            target = normalize_code(code)
            if target is None:
                print(f"  [跳过] {Path(path).name} 第{line_no}行 {name}: 编号 {code!r} 无有效数字")
                continue
            rows.append(
                (
                    Path(path).name,
                    line_no,
                    target,
                    str(name).strip(),
                    normalize_brand(brand),
                    normalize_spec(spec),
                )
            )
    return rows


def build_plan(rows, cursor):
    """Build the rename plan {old_id: new_id}; return (plan, details, problems)."""
    db_skus = {}
    cursor.execute(
        "SELECT s.id, i.name, s.brand, s.spec FROM item_sku s JOIN item i ON i.id = s.item_id"
    )
    for sku_id, name, brand, spec in cursor.fetchall():
        key = (name, normalize_brand(brand), normalize_spec(spec))
        db_skus.setdefault(key, []).append(sku_id)
    used_ids = {sid for ids in db_skus.values() for sid in ids}

    # Duplicate target ids within the Excel files (one id can belong to only one SKU)
    target_count = {}
    for _, _, target, *_ in rows:
        target_count[target] = target_count.get(target, 0) + 1
    duplicated_targets = {t for t, n in target_count.items() if n > 1}

    plan = {}
    details = []
    problems = []
    for fname, line, target, name, brand, spec in rows:
        label = f"{name}（{fname} 第{line}行）"
        if target in duplicated_targets:
            problems.append(f"[编号重复] {label}: 目标编号 {target} 在 Excel 中出现多次，已跳过")
            continue
        hits = db_skus.get((name, brand, spec), [])
        if not hits:
            problems.append(f"[未匹配] {label}: 数据库中找不到 {name}/{brand or '(无品牌)'}/{spec}")
            continue
        if len(hits) > 1:
            problems.append(f"[匹配多个] {label}: 匹配到多个 SKU {hits}，已跳过")
            continue
        old_id = hits[0]
        if old_id == target:
            details.append((old_id, target, name, "编号已正确，无需修改"))
            continue
        if target in used_ids:
            problems.append(f"[目标被占用] {label}: 目标编号 {target} 已被其他 SKU 使用，已跳过")
            continue
        if old_id in plan:
            problems.append(f"[重复映射] {label}: SKU {old_id} 已有其他改名计划，已跳过")
            continue
        plan[old_id] = target
        details.append((old_id, target, name, ""))
    return plan, details, problems


def count_references(cursor, sku_id):
    counts = {}
    for table, column in FK_REFERENCES:
        cursor.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = ?', (sku_id,))
        counts[table] = cursor.fetchone()[0]
    return counts


def apply_plan(cursor, plan):
    """Two-phase rename: move to temporary negative ids first, then to targets."""
    for old_id, new_id in plan.items():
        temp_id = -old_id
        cursor.execute("UPDATE item_sku SET id = ? WHERE id = ?", (temp_id, old_id))
        for table, column in FK_REFERENCES:
            cursor.execute(
                f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?',
                (temp_id, old_id),
            )
    for old_id, new_id in plan.items():
        temp_id = -old_id
        cursor.execute("UPDATE item_sku SET id = ? WHERE id = ?", (new_id, temp_id))
        for table, column in FK_REFERENCES:
            cursor.execute(
                f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?',
                (new_id, temp_id),
            )


def main():
    parser = argparse.ArgumentParser(description="根据入库明细 Excel 修正物品编号（item_sku.id）")
    parser.add_argument("excel", nargs="+", help="入库明细 Excel 文件路径（可多个）")
    parser.add_argument("--db-path", default="data.db", help="数据库文件路径（默认 data.db）")
    parser.add_argument("--execute", action="store_true", help="实际执行修改（默认为 dry-run 预览）")
    args = parser.parse_args()

    dry_run = not args.execute
    print("=== DRY-RUN 预览模式（加 --execute 才会真正修改） ===\n" if dry_run else "=== 执行模式 ===\n")

    rows = read_excel_rows(args.excel)
    print(f"从 {len(args.excel)} 个 Excel 读取到 {len(rows)} 行有效数据\n")

    conn = sqlite3.connect(args.db_path)
    conn.isolation_level = None  # manual transactions; PRAGMA foreign_keys is a no-op inside one
    cursor = conn.cursor()

    plan, details, problems = build_plan(rows, cursor)

    print("--- 改名计划（旧编号 -> 新编号） ---")
    for old_id, new_id, name, note in sorted(details, key=lambda d: d[1]):
        refs = count_references(cursor, old_id)
        ref_str = ", ".join(f"{t}:{n}" for t, n in refs.items() if n) or "无关联记录"
        suffix = f"  [跳过: {note}]" if note else ""
        print(f"  {old_id} -> {new_id}  {name}  ({ref_str}){suffix}")

    if problems:
        print("\n--- 需要人工处理的问题 ---")
        for p in problems:
            print(f"  {p}")

    print(f"\n计划修改 {len(plan)} 个 SKU 编号，跳过 {len(details) - len(plan)} 个，问题 {len(problems)} 个")

    cursor.execute(f"SELECT COUNT(*) FROM item_sku WHERE {_DIRTY_BRAND_WHERE}")
    dirty_brands = cursor.fetchone()[0]
    if dirty_brands:
        print(f'另有 {dirty_brands} 个 SKU 的品牌为空/nan，将统一改为"{DEFAULT_BRAND}"')

    if dry_run:
        conn.close()
        return
    if not plan and not dirty_brands:
        print("没有需要修改的内容。")
        conn.close()
        return

    response = input("\n确认修改数据库？将先自动备份。(yes/no): ")
    if response.lower() != "yes":
        print("已取消。")
        conn.close()
        return

    backup = f"{args.db_path}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(args.db_path, backup)
    print(f"已备份数据库到 {backup}")

    try:
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN")
        apply_plan(cursor, plan)
        cursor.execute(
            f"UPDATE item_sku SET brand = ? WHERE {_DIRTY_BRAND_WHERE}",
            (DEFAULT_BRAND,),
        )
        fixed_brands = cursor.rowcount
        cursor.execute("COMMIT")
        cursor.execute("PRAGMA foreign_keys = ON")

        cursor.execute("PRAGMA foreign_key_check")
        violations = cursor.fetchall()
        if violations:
            print(f"警告: 外键检查发现 {len(violations)} 处违规，请恢复备份 {backup}")
            sys.exit(1)

        if fixed_brands:
            print(f'已将 {fixed_brands} 个 SKU 的脏品牌统一改为"{DEFAULT_BRAND}"')
        if plan:
            print("\n修改完成，外键检查通过。最终结果：")
            cursor.execute(
                "SELECT s.id, i.name, s.brand, s.spec FROM item_sku s JOIN item i ON i.id = s.item_id "
                f"WHERE s.id IN ({','.join('?' * len(plan))}) ORDER BY s.id",
                tuple(plan.values()),
            )
            for row in cursor.fetchall():
                print(f"  {row}")
        else:
            print("\n修改完成，外键检查通过。")
    except Exception as e:
        cursor.execute("ROLLBACK")
        print(f"出错已回滚: {e}，数据库备份在 {backup}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

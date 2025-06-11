from flask import render_template, request, redirect, url_for, send_file, flash
from flask_login import login_required, current_user
from wms import app, db
from wms.utils import admin_required
from wms.models import (
    Receipt,
    ReceiptType,
    Warehouse,
    WarehouseItemSKU,
    Area,
    Department,
    Transaction,
    ItemSKU,
    Item,
    User,
)
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_, select, distinct
from io import BytesIO
from decimal import Decimal
import pandas as pd


@app.route("/records", methods=["GET"])
@login_required
def records():
    # Get all unique item names for datalist
    item_names = (
        db.session.execute(select(distinct(Item.name)).order_by(Item.name))
        .scalars()
        .all()
    )

    # Get filter parameters from request
    record_type = request.args.get(
        "type", "stockout"
    )  # stockin, stockout or takestock (default to stockout)
    warehouse_id = request.args.get("warehouse")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    refcode = request.args.get("refcode")
    location_info = request.args.get("location_info")
    item_name = request.args.get("item_name")
    sku_desc = request.args.get("sku_desc")
    page = request.args.get("page", 1, type=int)
    per_page = 20

    # Get warehouses accessible by the current user
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        # Regular users can only see public warehouses and their own warehouse
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

    # For regular users, ensure a warehouse is selected
    if not current_user.is_admin and not warehouse_id and warehouses:
        # Default to user's own warehouse if available, otherwise first available warehouse
        user_warehouse = next(
            (w for w in warehouses if w.owner_id == current_user.id), None
        )
        default_warehouse = user_warehouse or warehouses[0] if warehouses else None

        if default_warehouse:
            # Redirect to same page with default warehouse selected
            return redirect(
                url_for(
                    "records",
                    warehouse=default_warehouse.id,
                    type=record_type,
                    start_date=start_date,
                    end_date=end_date,
                    refcode=refcode,
                    location_info=location_info,
                    item_name=item_name,
                    sku_desc=sku_desc,
                )
            )

    # Query base - join necessary relationships
    query = (
        db.session.query(Transaction)
        .join(Receipt)
        .join(Warehouse)
        .join(ItemSKU)
        .join(Item)
        .options(
            joinedload(Transaction.receipt).joinedload(Receipt.warehouse),
            joinedload(Transaction.receipt).joinedload(Receipt.operator),
            joinedload(Transaction.receipt).joinedload(Receipt.area),
            joinedload(Transaction.receipt).joinedload(Receipt.department),
            joinedload(Transaction.itemSKU).joinedload(ItemSKU.item),
        )
        .order_by(Receipt.date.desc(), Transaction.id.asc())
    )

    # Filter by user's warehouse access if not admin
    if not current_user.is_admin:
        query = query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        )

    # Apply filters
    if record_type == "stockin":
        query = query.filter(Receipt.type == ReceiptType.STOCKIN)
    elif record_type == "takestock":
        query = query.filter(Receipt.type == ReceiptType.TAKESTOCK)
    else:
        query = query.filter(Receipt.type == ReceiptType.STOCKOUT)
        if location_info:
            # Search area or department name if provided
            query = (
                query.outerjoin(Area)
                .outerjoin(Department)
                .filter(
                    (Area.name.ilike(f"%{location_info}%"))
                    | (Department.name.ilike(f"%{location_info}%"))
                    | (Receipt.location.ilike(f"%{location_info}%"))
                )
            )

    if warehouse_id:
        # For non-admins, ensure they can only access their warehouse or public warehouses
        if not current_user.is_admin:
            allowed_warehouse_ids = [w.id for w in warehouses]
            if int(warehouse_id) not in allowed_warehouse_ids:
                warehouse_id = None

        if warehouse_id:
            query = query.filter(Receipt.warehouse_id == warehouse_id)

    if start_date:
        start_datetime = datetime.strptime(
            f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"
        )
        query = query.filter(Receipt.date >= start_datetime)

    if end_date:
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        query = query.filter(Receipt.date <= end_datetime)

    if refcode and record_type == "stockin":
        query = query.filter(Receipt.refcode.ilike(f"%{refcode}%"))

    # Add new filters for item name and SKU description
    if item_name:
        query = query.filter(Item.name.ilike(f"%{item_name}%"))

    if sku_desc:
        query = query.filter(
            (ItemSKU.brand.ilike(f"%{sku_desc}%"))
            | (ItemSKU.spec.ilike(f"%{sku_desc}%"))
        )

    # Paginate results - now based on transactions
    pagination = query.paginate(page=page, per_page=per_page)

    return render_template(
        "records.html.jinja",
        pagination=pagination,
        warehouses=warehouses,
        record_type=record_type,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        refcode=refcode,
        location_info=location_info,
        item_name=item_name,
        sku_desc=sku_desc,
        item_names=item_names,
        request=request,
    )


@app.route("/statistics_fee", methods=["GET"])
@login_required
@admin_required
def statistics_fee():
    # Get current year and month for default date range
    today = datetime.now()
    current_year = today.year
    current_month = today.month

    # Set default date range to current month if not provided
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    # If no dates are provided, default to current month
    if not start_date and not end_date:
        # First day of current month
        start_date = f"{current_year}-{current_month:02d}-01"

        # Last day of current month - calculate based on the next month's first day minus one day
        if current_month == 12:
            next_month_year = current_year + 1  # pragma: no cover
            next_month = 1  # pragma: no cover
        else:
            next_month_year = current_year
            next_month = current_month + 1

        # Create first day of next month
        next_month_first = datetime(next_month_year, next_month, 1)
        # Subtract one day to get last day of current month
        last_day = (next_month_first - timedelta(days=1)).day
        end_date = f"{current_year}-{current_month:02d}-{last_day}"

    # Initialize empty data structures
    warehouses = Warehouse.query.order_by(Warehouse.id).all()
    areas = Area.query.order_by(Area.id).all()
    departments = Department.query.order_by(Department.id).all()

    # Initialize statistics data structure with Decimal(0) instead of 0
    stats_data = {
        "warehouses": {w.id: {"name": w.name} for w in warehouses},
        "areas": {
            a.id: {"name": a.name, "departments": {}, "total": Decimal("0")}
            for a in areas
        },
        "departments": {
            d.id: {"name": d.name, "total": Decimal("0")} for d in departments
        },
        "total_by_warehouse": {w.id: Decimal("0") for w in warehouses},
        "grand_total": Decimal("0"),
    }

    # Initialize each cell in the warehouse × area × department structure
    for warehouse in warehouses:
        stats_data["warehouses"][warehouse.id]["areas"] = {}
        for area in areas:
            stats_data["warehouses"][warehouse.id]["areas"][area.id] = {
                "total": 0,
                "departments": {},
            }
            for department in departments:
                stats_data["warehouses"][warehouse.id]["areas"][area.id]["departments"][
                    department.id
                ] = 0

    # Process filter date range
    filter_conditions = [
        Receipt.type == ReceiptType.STOCKOUT,
        Receipt.revoked.is_(False),
    ]

    if start_date:
        start_datetime = datetime.strptime(
            f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"
        )
        filter_conditions.append(Receipt.date >= start_datetime)

    if end_date:
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        filter_conditions.append(Receipt.date <= end_datetime)

    # Query aggregating transactions by warehouse, area, and department
    results = (
        db.session.query(
            Receipt.warehouse_id,
            Receipt.area_id,
            Receipt.department_id,
            func.sum(Transaction.count * Transaction.price * Decimal("-1")).label(
                "total_value"
            ),
        )
        .join(Transaction)
        .filter(and_(*filter_conditions))
        .filter(
            Transaction.count < 0
        )  # Only include negative counts which are real stockouts
        .group_by(Receipt.warehouse_id, Receipt.area_id, Receipt.department_id)
        .all()
    )

    # Populate the statistics data structure
    for warehouse_id, area_id, department_id, total_value in results:
        # Skip entries with no area or department
        if not area_id or not department_id:
            continue

        # Keep as Decimal for precision
        value = total_value

        # Update values in the nested structure
        stats_data["warehouses"][warehouse_id]["areas"][area_id]["departments"][
            department_id
        ] = value

        # Update area total for this warehouse
        stats_data["warehouses"][warehouse_id]["areas"][area_id]["total"] += value

        # Update warehouse total
        stats_data["total_by_warehouse"][warehouse_id] += value

        # Update area total
        stats_data["areas"][area_id]["total"] += value

        # Update department total
        stats_data["departments"][department_id]["total"] += value

        # Update area total
        if area_id not in stats_data["areas"]:
            stats_data["areas"][area_id] = {
                "total": Decimal("0"),
                "departments": {},
            }
        if department_id not in stats_data["areas"][area_id]["departments"]:
            stats_data["areas"][area_id]["departments"][department_id] = Decimal("0")
        stats_data["areas"][area_id]["departments"][department_id] += value

        # Update grand total
        stats_data["grand_total"] += value

    return render_template(
        "statistics_fee.html.jinja",
        start_date=start_date,
        end_date=end_date,
        warehouses=warehouses,
        areas=areas,
        departments=departments,
        stats_data=stats_data,
        current_year=current_year,
        current_month=current_month,
    )


@app.route("/statistics_usage", methods=["GET"])
@login_required
def statistics_usage():
    # Get current year and month for default date range
    today = datetime.now()
    current_year = today.year
    current_month = today.month

    # Get filter parameters from request
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    warehouse_id = request.args.get("warehouse")
    item_name = request.args.get("item_name", "")
    brand = request.args.get("brand", "")
    spec = request.args.get("spec", "")

    # If no dates are provided, default to current month
    if not start_date and not end_date:
        # First day of current month
        start_date = f"{current_year}-{current_month:02d}-01"

        # Last day of current month
        if current_month == 12:
            next_month_year = current_year + 1  # pragma: no cover
            next_month = 1  # pragma: no cover
        else:
            next_month_year = current_year
            next_month = current_month + 1
        next_month_first = datetime(next_month_year, next_month, 1)
        last_day = (next_month_first - timedelta(days=1)).day
        end_date = f"{current_year}-{current_month:02d}-{last_day}"

    # Get warehouses accessible by the current user
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

    # For regular users, ensure a warehouse is selected
    if not current_user.is_admin and not warehouse_id and warehouses:
        user_warehouse = next(
            (w for w in warehouses if w.owner_id == current_user.id), None
        )
        default_warehouse = user_warehouse or warehouses[0] if warehouses else None
        if default_warehouse:
            return redirect(
                url_for(
                    "statistics_usage",
                    warehouse=default_warehouse.id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

    # Get all unique item names for datalist
    item_names = (
        db.session.execute(select(distinct(Item.name)).order_by(Item.name))
        .scalars()
        .all()
    )

    # Query base - aggregate transactions by ItemSKU and get average price from warehouse
    # We need to join with WarehouseItemSKU to get the current average price
    if warehouse_id:
        # For specific warehouse, get the average price from that warehouse
        query = (
            db.session.query(
                ItemSKU,
                Item,
                func.sum(Transaction.count * -1).label("total_usage"),
                WarehouseItemSKU.average_price.label("average_price"),
            )
            .join(Transaction)
            .join(Receipt)
            .join(Item)
            .outerjoin(
                WarehouseItemSKU,
                (WarehouseItemSKU.itemSKU_id == ItemSKU.id)
                & (WarehouseItemSKU.warehouse_id == warehouse_id),
            )
            .filter(Receipt.type == ReceiptType.STOCKOUT)
            .filter(Receipt.revoked.is_(False))
            .filter(
                Transaction.count < 0
            )  # Only include negative counts which are real stockouts
            .group_by(ItemSKU.id, Item.id, WarehouseItemSKU.average_price)
            .order_by(Item.name, ItemSKU.brand, ItemSKU.spec)
        )
    else:
        # For all warehouses, calculate weighted average price
        query = (
            db.session.query(
                ItemSKU,
                Item,
                func.sum(Transaction.count * -1).label("total_usage"),
                func.avg(WarehouseItemSKU.average_price).label("average_price"),
            )
            .join(Transaction)
            .join(Receipt)
            .join(Item)
            .outerjoin(WarehouseItemSKU, WarehouseItemSKU.itemSKU_id == ItemSKU.id)
            .filter(Receipt.type == ReceiptType.STOCKOUT)
            .filter(Receipt.revoked.is_(False))
            .filter(
                Transaction.count < 0
            )  # Only include negative counts which are real stockouts
            .group_by(ItemSKU.id, Item.id)
            .order_by(Item.name, ItemSKU.brand, ItemSKU.spec)
        )

    # Filter by warehouse access if not admin
    if not current_user.is_admin:
        query = query.join(Receipt.warehouse).filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        )

    # Apply filters
    if warehouse_id:
        if not current_user.is_admin:
            allowed_warehouse_ids = [w.id for w in warehouses]
            if int(warehouse_id) not in allowed_warehouse_ids:
                warehouse_id = None

        if warehouse_id:
            query = query.filter(Receipt.warehouse_id == warehouse_id)

    if start_date:
        start_datetime = datetime.strptime(
            f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"
        )
        query = query.filter(Receipt.date >= start_datetime)

    if end_date:
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        query = query.filter(Receipt.date <= end_datetime)

    # Apply item filters
    if item_name:
        query = query.filter(Item.name.ilike(f"%{item_name}%"))
    if brand:
        query = query.filter(ItemSKU.brand.ilike(f"%{brand}%"))
    if spec:
        query = query.filter(ItemSKU.spec.ilike(f"%{spec}%"))

    # Get results
    usage_data = query.all()

    # Calculate totals
    total_quantity = sum(data.total_usage for data in usage_data)
    total_value = sum(
        (data.total_usage * (data.average_price or 0)) for data in usage_data
    )

    return render_template(
        "statistics_usage.html.jinja",
        warehouses=warehouses,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        usage_data=usage_data,
        current_year=current_year,
        current_month=current_month,
        item_names=item_names,
        item_name=item_name,
        brand=brand,
        spec=spec,
        total_quantity=total_quantity,
        total_value=total_value,
    )


@app.route("/records/export")
@login_required
def records_export():
    # Get filter parameters from request - same as records route
    record_type = request.args.get("type", "stockout")
    warehouse_id = request.args.get("warehouse")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    refcode = request.args.get("refcode")
    location_info = request.args.get("location_info")
    item_name = request.args.get("item_name")
    sku_desc = request.args.get("sku_desc")

    # Get warehouses accessible by the current user
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

    # Build the base query with explicit join order
    query = (
        db.session.query(
            Receipt.date,
            Item.name.label("item_name"),
            ItemSKU.brand,
            ItemSKU.spec,
            Transaction.count,
            Transaction.price,
            Warehouse.name.label("warehouse_name"),
            Receipt.refcode,
            User.nickname.label("operator_name"),
            Area.name.label("area_name"),
            Department.name.label("department_name"),
            Receipt.location,
            Receipt.note,
        )
        .select_from(Transaction)
        .join(Receipt, Transaction.receipt_id == Receipt.id)
        .join(ItemSKU, Transaction.itemSKU_id == ItemSKU.id)
        .join(Item, ItemSKU.item_id == Item.id)
        .join(Warehouse, Receipt.warehouse_id == Warehouse.id)
        .outerjoin(User, Receipt.operator_id == User.id)
        .outerjoin(Area, Receipt.area_id == Area.id)
        .outerjoin(Department, Receipt.department_id == Department.id)
    )

    # Apply filters
    if not current_user.is_admin:
        query = query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        )

    # Filter out revoked receipts
    query = query.filter(Receipt.revoked.is_(False))

    if record_type == "stockin":
        query = query.filter(Receipt.type == ReceiptType.STOCKIN)
    elif record_type == "takestock":
        query = query.filter(Receipt.type == ReceiptType.TAKESTOCK)
    else:
        query = query.filter(Receipt.type == ReceiptType.STOCKOUT)
        if location_info:
            query = query.filter(
                (Area.name.ilike(f"%{location_info}%"))
                | (Department.name.ilike(f"%{location_info}%"))
                | (Receipt.location.ilike(f"%{location_info}%"))
            )

    if warehouse_id:
        if not current_user.is_admin:
            allowed_warehouse_ids = [w.id for w in warehouses]
            if int(warehouse_id) not in allowed_warehouse_ids:
                warehouse_id = None

        if warehouse_id:
            query = query.filter(Receipt.warehouse_id == warehouse_id)

    if start_date:
        start_datetime = datetime.strptime(
            f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"
        )
        query = query.filter(Receipt.date >= start_datetime)

    if end_date:
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        query = query.filter(Receipt.date <= end_datetime)

    if refcode and record_type == "stockin":
        query = query.filter(Receipt.refcode.ilike(f"%{refcode}%"))

    if item_name:
        query = query.filter(Item.name.ilike(f"%{item_name}%"))

    if sku_desc:
        query = query.filter(
            (ItemSKU.brand.ilike(f"%{sku_desc}%"))
            | (ItemSKU.spec.ilike(f"%{sku_desc}%"))
        )

    # Execute query and convert to pandas DataFrame
    results = query.all()
    df = pd.DataFrame([r._asdict() for r in results])

    if not df.empty:
        # Format the data
        df["date"] = df["date"].dt.strftime("%Y-%m-%d %H:%M")
        df["count"] = df.apply(
            lambda x: x["count"] if record_type == "stockin" else -x["count"], axis=1
        )
        df["price"] = df["price"].apply(lambda x: "{:.2f}".format(float(x)))

        # Select and rename columns based on record type
        if record_type == "stockin":
            columns = {
                "date": "日期",
                "item_name": "物品",
                "brand": "品牌",
                "spec": "规格",
                "count": "数量",
                "price": "价格",
                "warehouse_name": "仓库",
                "refcode": "单号",
            }
        elif record_type == "takestock":
            columns = {
                "date": "日期",
                "item_name": "物品",
                "brand": "品牌",
                "spec": "规格",
                "count": "数量",
                "price": "价格",
                "warehouse_name": "仓库",
                "operator_name": "操作员",
                "note": "备注",
            }
        else:
            columns = {
                "date": "日期",
                "item_name": "物品",
                "brand": "品牌",
                "spec": "规格",
                "count": "数量",
                "price": "价格",
                "warehouse_name": "仓库",
                "operator_name": "操作员",
                "area_name": "区域",
                "department_name": "部门",
                "location": "具体地点",
                "note": "备注",
            }

        df = df[columns.keys()].rename(columns=columns)

    # Create Excel file in memory
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False, engine="openpyxl")
    excel_file.seek(0)

    # Get warehouse name for filename
    warehouse_name = "全部仓库"
    if warehouse_id:
        warehouse = next((w for w in warehouses if w.id == int(warehouse_id)), None)
        if warehouse:
            warehouse_name = warehouse.name

    # Generate filename
    filename = (
        f"records_{warehouse_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/receipt/<int:receipt_id>")
@login_required
def receipt_detail(receipt_id):
    """Show receipt details and provide revocation interface if applicable"""
    # Get receipt with all relationships loaded
    receipt = (
        db.session.query(Receipt)
        .options(
            joinedload(Receipt.transactions)
            .joinedload(Transaction.itemSKU)
            .joinedload(ItemSKU.item),
            joinedload(Receipt.warehouse),
            joinedload(Receipt.operator),
            joinedload(Receipt.area),
            joinedload(Receipt.department),
        )
        .filter(Receipt.id == receipt_id)
        .first_or_404()
    )

    # Check if user has access to this receipt's warehouse
    if not current_user.is_admin:
        warehouse_accessible = (
            receipt.warehouse.is_public or receipt.warehouse.owner_id == current_user.id
        )
        if not warehouse_accessible:
            flash("您没有权限查看此单据", "danger")
            return redirect(url_for("records"))

    # Check if user can revoke this receipt
    can_revoke = False
    is_admin = current_user.is_admin

    # Admin can revoke any receipt
    if is_admin:
        can_revoke = True
    else:
        # Regular users can only revoke receipts in their warehouse and within 24h
        time_limit = datetime.now() - timedelta(hours=24)
        warehouse_owned = receipt.warehouse.owner_id == current_user.id
        recent_enough = receipt.date >= time_limit
        can_revoke = warehouse_owned and recent_enough

    # Create revoke form
    from wms.forms import RevokeReceiptForm

    revoke_form = RevokeReceiptForm()

    return render_template(
        "receipt_detail.html.jinja",
        receipt=receipt,
        can_revoke=can_revoke,
        is_admin=is_admin,
        revoke_form=revoke_form,
    )


@app.route("/receipt/<int:receipt_id>/revoke", methods=["POST"])
@login_required
def revoke_receipt(receipt_id):
    """Handle receipt revocation"""
    from wms.forms import RevokeReceiptForm

    form = RevokeReceiptForm()

    receipt = db.session.get(Receipt, receipt_id)
    if not receipt:
        flash("单据不存在", "danger")
        return redirect(url_for("records"))

    # Check if receipt is already revoked
    if receipt.revoked:
        flash("此单据已被撤销", "warning")
        return redirect(url_for("receipt_detail", receipt_id=receipt_id))

    # Check permissions
    if not current_user.is_admin:
        # Check if user owns the warehouse
        warehouse_owned = receipt.warehouse.owner_id == current_user.id
        if not warehouse_owned:
            flash("您没有权限撤销此单据", "danger")
            return redirect(url_for("receipt_detail", receipt_id=receipt_id))

        # Check 24h time limit for regular users
        time_limit = datetime.now() - timedelta(hours=24)
        if receipt.date < time_limit:
            flash("您只能撤销24小时内的单据，请联系管理员", "danger")
            return redirect(url_for("receipt_detail", receipt_id=receipt_id))

    # Validate the form
    if form.validate_on_submit():
        reason = form.reason.data
    else:
        flash("请提供撤销原因", "danger")
        return redirect(url_for("receipt_detail", receipt_id=receipt_id))

    # Prepare the note with revocation reason and operator info
    revoke_note = f"已撤销：{reason} (由 {current_user.nickname} 操作)"
    if receipt.note:
        # Append to existing note if there is one
        receipt.note = f"{receipt.note}； {revoke_note}"
    else:
        receipt.note = revoke_note

    # Mark as revoked
    receipt.revoked = True

    # Revert inventory changes by creating a counter receipt
    # Creating a new receipt with opposite transactions for inventory
    counter_receipt = Receipt(
        operator=current_user,
        warehouse_id=receipt.warehouse_id,
        type=receipt.type,  # Same type as original
        area_id=receipt.area_id,
        department_id=receipt.department_id,
        location=receipt.location,
        note=f"撤销单据 {receipt.refcode} 的库存变更：{reason}",
    )

    if receipt.refcode:
        counter_receipt.refcode = f"RV-{receipt.refcode}"

    db.session.add(counter_receipt)
    db.session.flush()  # To get the counter receipt ID

    # Create opposite transactions
    for transaction in receipt.transactions:
        counter_transaction = Transaction(
            itemSKU_id=transaction.itemSKU_id,
            count=-transaction.count,  # Opposite of original
            price=transaction.price,
            receipt_id=counter_receipt.id,
        )
        db.session.add(counter_transaction)

    try:
        db.session.commit()
        # Update warehouse inventory with the counter transactions
        counter_receipt.update_warehouse_item_skus()
        db.session.commit()
        flash("单据已成功撤销", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"撤销单据时出错: {str(e)}", "danger")

    return redirect(url_for("receipt_detail", receipt_id=receipt_id))

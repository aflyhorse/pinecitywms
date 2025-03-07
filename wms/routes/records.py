from flask import render_template, request, redirect, url_for, send_file
from flask_login import login_required, current_user
from wms import app, db
from wms.utils import admin_required
from wms.models import (
    Receipt,
    ReceiptType,
    Warehouse,
    Customer,
    Transaction,
    ItemSKU,
    Item,
    CustomerType,
)
from datetime import datetime
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_, select, distinct
from openpyxl import Workbook
from io import BytesIO


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
    )  # stockin or stockout (default to stockout)
    warehouse_id = request.args.get("warehouse")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    refcode = request.args.get("refcode")
    customer = request.args.get("customer")
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
                    customer=customer,
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
            joinedload(Transaction.receipt).joinedload(Receipt.customer),
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
    else:
        query = query.filter(Receipt.type == ReceiptType.STOCKOUT)
        if customer:
            # Search customer name if provided
            query = query.join(Customer).filter(Customer.name.ilike(f"%{customer}%"))

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
        customer=customer,
        item_name=item_name,
        sku_desc=sku_desc,
        item_names=item_names,
        request=request,
    )


@app.route("/statistics_fee", methods=["GET"])
@login_required
@admin_required
def statistics_fee():
    # Get filter parameters from request
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    # Current year and month for shortcut buttons
    today = datetime.now()
    current_year = today.year
    current_month = today.month

    # Initialize empty data structures
    warehouses = Warehouse.query.order_by(Warehouse.name).all()
    customers_by_type = {}
    all_customers = []

    # Get all customers grouped by type
    for customer_type in CustomerType:
        customers = (
            Customer.query.filter_by(type=customer_type).order_by(Customer.name).all()
        )
        customers_by_type[customer_type.name] = customers
        all_customers.extend(customers)

    # Sort all customers by name for consistent display
    all_customers.sort(key=lambda x: x.name)

    # Initialize statistics table data structure
    stats_data = {
        "warehouses": {w.id: {"name": w.name, "customers": {}} for w in warehouses},
        "total_by_warehouse": {w.id: 0 for w in warehouses},
        "total_by_customer": {c.id: 0 for c in all_customers},
        "grand_total": 0,
    }

    # Initialize each cell in the table (warehouse x customer)
    for warehouse in warehouses:
        for customer in all_customers:
            stats_data["warehouses"][warehouse.id]["customers"][customer.id] = 0

    # Process filter date range
    filter_conditions = [Receipt.type == ReceiptType.STOCKOUT]

    if start_date:
        start_datetime = datetime.strptime(
            f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S"
        )
        filter_conditions.append(Receipt.date >= start_datetime)

    if end_date:
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        filter_conditions.append(Receipt.date <= end_datetime)

    # Query for aggregated data
    if start_date or end_date:
        # Query aggregating transactions by warehouse and customer
        results = (
            db.session.query(
                Receipt.warehouse_id,
                Receipt.customer_id,
                func.sum(Transaction.count * Transaction.price * -1).label(
                    "total_value"
                ),
            )
            .join(Transaction)
            .filter(and_(*filter_conditions))
            .group_by(Receipt.warehouse_id, Receipt.customer_id)
            .all()
        )

        # Populate the statistics data structure
        for warehouse_id, customer_id, total_value in results:
            # Skip entries with no customer (shouldn't happen for STOCKOUT)
            if not customer_id:
                continue  # pragma: no cover

            # Update cell value
            stats_data["warehouses"][warehouse_id]["customers"][customer_id] = float(
                total_value
            )

            # Update row total (by warehouse)
            stats_data["total_by_warehouse"][warehouse_id] += float(total_value)

            # Update column total (by customer)
            stats_data["total_by_customer"][customer_id] += float(total_value)

            # Update grand total
            stats_data["grand_total"] += float(total_value)

    return render_template(
        "statistics_fee.html.jinja",
        start_date=start_date,
        end_date=end_date,
        warehouses=warehouses,
        customers_by_type=customers_by_type,
        all_customers=all_customers,
        stats_data=stats_data,
        current_year=current_year,
        current_month=current_month,
    )


@app.route("/export_records")
@login_required
def export_records():
    # Get filter parameters from request - same as records route
    record_type = request.args.get("type", "stockout")
    warehouse_id = request.args.get("warehouse")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    refcode = request.args.get("refcode")
    customer = request.args.get("customer")
    item_name = request.args.get("item_name")
    sku_desc = request.args.get("sku_desc")

    # Get warehouses accessible by the current user - same as records route
    if current_user.is_admin:
        warehouses = Warehouse.query.all()
    else:
        warehouses = Warehouse.query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        ).all()

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
            joinedload(Transaction.receipt).joinedload(Receipt.customer),
            joinedload(Transaction.itemSKU).joinedload(ItemSKU.item),
        )
        .order_by(Receipt.date.desc(), Transaction.id.asc())
    )

    # Apply all the same filters as the records route
    if not current_user.is_admin:
        query = query.filter(
            (Warehouse.is_public.is_(True)) | (Warehouse.owner_id == current_user.id)
        )

    if record_type == "stockin":
        query = query.filter(Receipt.type == ReceiptType.STOCKIN)
    else:
        query = query.filter(Receipt.type == ReceiptType.STOCKOUT)
        if customer:
            query = query.join(Customer).filter(Customer.name.ilike(f"%{customer}%"))

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

    # Get all results for export
    transactions = query.all()

    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "操作记录"

    # Write headers
    headers = ["日期", "物品", "规格", "数量", "价格", "仓库"]
    if record_type == "stockin":
        headers.append("单号")
    else:
        headers.extend(["操作员", "客户"])

    for col, header in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=header)

    # Write data
    for row, trans in enumerate(transactions, start=2):
        ws.cell(row=row, column=1, value=trans.receipt.date.strftime("%Y-%m-%d %H:%M"))
        ws.cell(row=row, column=2, value=trans.itemSKU.item.name)
        ws.cell(
            row=row, column=3, value=f"{trans.itemSKU.brand} - {trans.itemSKU.spec}"
        )
        ws.cell(
            row=row,
            column=4,
            value=trans.count if record_type == "stockin" else -trans.count,
        )
        ws.cell(row=row, column=5, value=float(trans.price))
        ws.cell(row=row, column=6, value=trans.receipt.warehouse.name)

        if record_type == "stockin":
            ws.cell(row=row, column=7, value=trans.receipt.refcode)
        else:
            ws.cell(row=row, column=7, value=trans.receipt.operator.nickname)
            customer_name = (
                trans.receipt.customer.name if trans.receipt.customer else ""
            )
            ws.cell(row=row, column=8, value=customer_name)

    # Save to BytesIO
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    # Get warehouse name for filename
    warehouse_name = "全部仓库"
    if warehouse_id:
        warehouse = next((w for w in warehouses if w.id == int(warehouse_id)), None)
        if warehouse:
            warehouse_name = warehouse.name

    # Generate filename based on current datetime and warehouse
    filename = (
        f"records_{warehouse_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )

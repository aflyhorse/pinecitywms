from flask import render_template, request
from flask_login import login_required
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
from sqlalchemy import func, and_


@app.route("/records", methods=["GET"])
@login_required
@admin_required
def records():
    # Get filter parameters from request
    record_type = request.args.get("type", "stockin")  # stockin or stockout
    warehouse_id = request.args.get("warehouse")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    refcode = request.args.get("refcode")
    customer = request.args.get("customer")
    page = request.args.get("page", 1, type=int)
    per_page = 20

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

    # Apply filters
    if record_type == "stockin":
        query = query.filter(Receipt.type == ReceiptType.STOCKIN)
    else:
        query = query.filter(Receipt.type == ReceiptType.STOCKOUT)
        if customer:
            # Search customer name if provided
            query = query.join(Customer).filter(Customer.name.ilike(f"%{customer}%"))

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

    # Get all warehouses for the filter dropdown
    warehouses = Warehouse.query.all()

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
        request=request,
    )


@app.route("/statistics", methods=["GET"])
@login_required
@admin_required
def statistics():
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
                continue

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
        "statistics.html.jinja",
        start_date=start_date,
        end_date=end_date,
        warehouses=warehouses,
        customers_by_type=customers_by_type,
        all_customers=all_customers,
        stats_data=stats_data,
        current_year=current_year,
        current_month=current_month,
    )

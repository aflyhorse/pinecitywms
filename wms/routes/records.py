from flask import render_template, request
from flask_login import login_required
from wms import app, db
from wms.utils import admin_required
from wms.models import Receipt, ReceiptType, Warehouse, Customer, Transaction, ItemSKU, Item
from datetime import datetime
from sqlalchemy.orm import joinedload


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
        start_datetime = datetime.strptime(f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S")
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
        request=request
    )

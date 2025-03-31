from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    current_app,
    session,
)
from flask_login import current_user, login_required
from wms import app
from wms.models import (
    db,
    Warehouse,
    Item,
    ItemSKU,
    Receipt,
    Transaction,
    ReceiptType,
    WarehouseItemSKU,
)
from wms.forms import BatchStockInForm, BatchTakeStockForm
from wms.utils import admin_required
import pandas as pd
from datetime import datetime
from io import BytesIO
from decimal import Decimal


@app.route("/batch_stockin", methods=["GET", "POST"])
@login_required
@admin_required
def batch_stockin():
    """Batch stockin page"""
    form = BatchStockInForm()
    warehouses = db.session.execute(db.select(Warehouse)).scalars().all()
    form.warehouse.choices = [(w.id, w.name) for w in warehouses]

    # Set default warehouse from session if available
    if "last_warehouse_id" in session and request.method == "GET":
        last_warehouse_id = session["last_warehouse_id"]
        warehouse_ids = [w.id for w in warehouses]
        if last_warehouse_id in warehouse_ids:
            form.warehouse.data = last_warehouse_id

    if request.method == "POST" and form.validate_on_submit():
        # Get warehouse
        warehouse_id = form.warehouse.data
        warehouse = db.session.get(Warehouse, warehouse_id)
        if not warehouse:
            flash("仓库不存在", "error")
            return redirect(url_for("batch_stockin"))

        # Save selected warehouse to session
        session["last_warehouse_id"] = warehouse_id

        # Process the uploaded file
        uploaded_file = request.files["file"]
        if not uploaded_file:
            flash("请选择文件", "error")
            return redirect(url_for("batch_stockin"))

        # Check file extension
        if not uploaded_file.filename.endswith(".xlsx"):
            flash("请上传 Excel 文件 (.xlsx)", "error")
            return redirect(url_for("batch_stockin"))

        try:
            # Read the Excel file
            df = pd.read_excel(uploaded_file)

            # Verify columns
            required_columns = ["物品", "品牌", "规格", "数量", "单价"]
            for col in required_columns:
                if col not in df.columns:
                    flash(f"文件缺少必要的列: {col}", "error")
                    return redirect(url_for("batch_stockin"))

            # Generate refcode for this batch operation
            refcode = f"IMPORT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

            # Create the receipt for this batch operation
            receipt = Receipt(
                operator=current_user,
                refcode=refcode,
                warehouse_id=warehouse.id,
                type=ReceiptType.STOCKIN,
            )
            db.session.add(receipt)
            db.session.flush()  # Flush to get receipt ID

            # Process each row
            processed_count = 0
            for _, row in df.iterrows():
                item_name = str(row["物品"]).strip()
                brand = str(row["品牌"]).strip()
                spec = str(row["规格"]).strip()
                quantity = int(row["数量"]) if not pd.isna(row["数量"]) else 0
                price = Decimal(row["单价"]) if not pd.isna(row["单价"]) else Decimal(0)

                if (
                    not item_name
                    or not brand
                    or not spec
                    or item_name == "样例-LED长方形灯"
                ):
                    continue  # Skip incomplete rows

                # Find or create item
                item = db.session.execute(
                    db.select(Item).filter_by(name=item_name)
                ).scalar_one_or_none()

                if not item:
                    item = Item(name=item_name)
                    db.session.add(item)
                    db.session.flush()  # To get the item ID

                # Find or create item SKU
                item_sku = db.session.execute(
                    db.select(ItemSKU).filter_by(
                        item_id=item.id, brand=brand, spec=spec
                    )
                ).scalar_one_or_none()

                if not item_sku:
                    item_sku = ItemSKU(item_id=item.id, brand=brand, spec=spec)
                    db.session.add(item_sku)
                    db.session.flush()  # To get the SKU ID

                # Create transaction even if quantity=0
                transaction = Transaction(
                    itemSKU_id=item_sku.id,
                    count=quantity,
                    price=price,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
                processed_count += 1

            # Commit transactions
            db.session.commit()

            # Update warehouse inventory
            receipt.update_warehouse_item_skus()
            db.session.commit()

            flash(f"成功处理 {processed_count} 条记录", "success")
            return redirect(url_for("batch_stockin"))
        except Exception as e:
            db.session.rollback()
            flash(f"处理文件时出错: {str(e)}", "error")
            current_app.logger.error(f"Batch stockin error: {e}")
            return redirect(url_for("batch_stockin"))

    return render_template("batch_stockin.html.jinja", form=form)


@app.route("/batch_stockin/template")
@login_required
@admin_required
def stockin_template():
    """Download stockin template"""
    # Create a DataFrame with the required columns
    df = pd.DataFrame(columns=["物品", "品牌", "规格", "数量", "单价"])

    # Add a sample row (optional)
    df.loc[0] = ["样例-LED长方形灯", "飞利浦", "10*20cm，8W 6500K", 10, 9.99]

    # Create Excel in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="入库模板")
    output.seek(0)

    # Send file to user
    return send_file(
        output,
        download_name="stockin_template.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/batch_takestock", methods=["GET", "POST"])
@login_required
def batch_takestock():
    """Batch take stock page"""
    form = BatchTakeStockForm()
    warehouses = db.session.execute(db.select(Warehouse)).scalars().all()
    form.warehouse.choices = [(w.id, w.name) for w in warehouses]

    # Set default warehouse from session if available
    if "last_warehouse_id" in session and request.method == "GET":
        last_warehouse_id = session["last_warehouse_id"]
        warehouse_ids = [w.id for w in warehouses]
        if last_warehouse_id in warehouse_ids:
            form.warehouse.data = last_warehouse_id

    if request.method == "POST":
        warehouse_id = form.warehouse.data
        warehouse = db.session.get(Warehouse, warehouse_id)
        if not warehouse:
            flash("仓库不存在", "error")
            return redirect(url_for("batch_takestock"))

        # Save selected warehouse to session
        session["last_warehouse_id"] = warehouse_id

        # Handle template download
        if "download_template" in request.form:
            only_with_stock = request.form.get("only_with_stock") == "y"
            return generate_takestock_template(warehouse, only_with_stock)

        # Handle file upload
        elif form.validate_on_submit():
            if not form.note.data:
                flash("请填写盘库说明", "error")  # pragma: no cover
                return redirect(url_for("batch_takestock"))  # pragma: no cover

            uploaded_file = request.files["file"]
            if not uploaded_file:
                flash("请选择文件", "error")  # pragma: no cover
                return redirect(url_for("batch_takestock"))  # pragma: no cover

            # Check file extension
            if not uploaded_file.filename.endswith(".xlsx"):
                flash("请上传 Excel 文件 (.xlsx)", "error")  # pragma: no cover
                return redirect(url_for("batch_takestock"))  # pragma: no cover

            try:
                # Read the Excel file
                df = pd.read_excel(uploaded_file)

                # Verify columns
                required_columns = ["物品", "品牌", "规格", "系统库存", "实际库存"]
                for col in required_columns:
                    if col not in df.columns:
                        flash(f"文件缺少必要的列: {col}", "error")
                        return redirect(url_for("batch_takestock"))

                # Generate refcode for this batch operation
                refcode = f"TAKESTOCK-{datetime.now().strftime('%Y%m%d%H%M%S')}"

                # Create the receipt for this batch operation
                receipt = Receipt(
                    operator=current_user,
                    refcode=refcode,
                    warehouse_id=warehouse.id,
                    type=ReceiptType.TAKESTOCK,
                    note=form.note.data,
                )
                db.session.add(receipt)
                db.session.flush()  # Flush to get receipt ID

                # Process each row
                processed_count = 0
                for _, row in df.iterrows():
                    item_name = str(row["物品"]).strip()
                    brand = str(row["品牌"]).strip()
                    spec = str(row["规格"]).strip()
                    system_count = (
                        int(row["系统库存"]) if not pd.isna(row["系统库存"]) else 0
                    )
                    actual_count = (
                        int(row["实际库存"]) if not pd.isna(row["实际库存"]) else 0
                    )

                    # Calculate the adjustment needed (actual - system)
                    delta_count = actual_count - system_count

                    if not item_name or not brand or not spec:
                        continue  # Skip incomplete rows  # pragma: no cover

                    # Find or create item
                    item = db.session.execute(
                        db.select(Item).filter_by(name=item_name)
                    ).scalar_one_or_none()

                    if not item:
                        item = Item(name=item_name)
                        db.session.add(item)
                        db.session.flush()  # To get the item ID

                    # Find or create item SKU
                    item_sku = db.session.execute(
                        db.select(ItemSKU).filter_by(
                            item_id=item.id, brand=brand, spec=spec
                        )
                    ).scalar_one_or_none()

                    if not item_sku:
                        item_sku = ItemSKU(item_id=item.id, brand=brand, spec=spec)
                        db.session.add(item_sku)
                        db.session.flush()  # To get the SKU ID

                    # Create transaction only if there's a change in count
                    if delta_count != 0:
                        transaction = Transaction(
                            itemSKU_id=item_sku.id,
                            price=0,
                            count=delta_count,
                            receipt_id=receipt.id,
                        )
                        db.session.add(transaction)
                        processed_count += 1

                # Commit transactions
                db.session.commit()

                # Update warehouse inventory
                receipt.update_warehouse_item_skus()
                db.session.commit()

                flash(f"成功处理 {processed_count} 条记录", "success")
                return redirect(url_for("batch_takestock"))
            except Exception as e:  # pragma: no cover
                db.session.rollback()
                flash(f"处理文件时出错: {str(e)}", "error")
                current_app.logger.error(f"Batch take stock error: {e}")
                return redirect(url_for("batch_takestock"))

    return render_template("batch_takestock.html.jinja", form=form)


def generate_takestock_template(warehouse, only_with_stock=False):
    """Generate take stock template for a warehouse"""
    # Query warehouse items with join to get item info
    query = (
        db.session.query(WarehouseItemSKU, Item.name, ItemSKU.brand, ItemSKU.spec)
        .join(ItemSKU, WarehouseItemSKU.itemSKU_id == ItemSKU.id)
        .join(Item, ItemSKU.item_id == Item.id)
        .filter(WarehouseItemSKU.warehouse_id == warehouse.id)
    )

    # Filter for items with count > 0 if requested
    if only_with_stock:
        query = query.filter(WarehouseItemSKU.count > 0)

    # Execute query and prepare data
    results = query.all()

    data = []
    for wis, item_name, brand, spec in results:
        data.append(
            {
                "物品": item_name,
                "品牌": brand,
                "规格": spec,
                "系统库存": wis.count,
                "实际库存": wis.count,  # Default value is same as system count
            }
        )

    # Create DataFrame
    df = pd.DataFrame(data)

    # Create Excel in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="盘库模板")
    output.seek(0)

    # Send file to user
    safe_name = warehouse.name.replace("/", "_").replace("\\", "_")
    return send_file(
        output,
        download_name=f"takestock_{safe_name}.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

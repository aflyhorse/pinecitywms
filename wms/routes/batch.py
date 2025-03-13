from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    current_app,
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
)
from wms.forms import BatchStockInForm
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

    if request.method == "POST" and form.validate_on_submit():
        # Get warehouse
        warehouse_id = form.warehouse.data
        warehouse = db.session.get(Warehouse, warehouse_id)
        if not warehouse:
            flash("仓库不存在", "error")
            return redirect(url_for("batch_stockin"))

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
            required_columns = ["物品", "品牌", "规格", "数量", "价格"]
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
                price = Decimal(row["价格"]) if not pd.isna(row["价格"]) else Decimal(0)

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

                # Create transaction for this item
                if quantity > 0:
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
    df = pd.DataFrame(columns=["物品", "品牌", "规格", "数量", "价格"])

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

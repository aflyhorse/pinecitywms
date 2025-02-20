from flask import render_template, url_for, redirect, flash
from flask_login import login_required, current_user
from wms import app, db
from wms.utils import admin_required
from wms.models import ItemSKU, Item, Warehouse, Receipt, Transaction, ReceiptType
from wms.forms import StockInForm


@app.route("/stockin", methods=["GET", "POST"])
@login_required
@admin_required
def stockin():
    form = StockInForm()
    # Get all items with their display text
    skus = db.session.query(ItemSKU).join(Item).all()
    items = [(sku.id, f"{sku.item.name} - {sku.brand} - {sku.spec}") for sku in skus]
    items_dict = dict(items)
    form.warehouse.choices = [(w.id, w.name) for w in Warehouse.query.all()]

    if form.validate_on_submit():
        receipt = Receipt(
            operator=current_user,
            refcode=form.refcode.data,
            warehouse_id=form.warehouse.data,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()

        for item_form in form.items:
            try:
                item_id = int(item_form.item_id.data)
                if item_id not in items_dict:
                    raise ValueError("Invalid item ID")

                transaction = Transaction(
                    itemSKU_id=item_id,
                    count=item_form.quantity.data,
                    price=item_form.price.data,
                    receipt_id=receipt.id,
                )
                db.session.add(transaction)
            except ValueError:
                flash(f"无效的物品: {item_form.item_id.data}", "danger")
                return render_template("stockin.html.jinja", form=form, items=items)

        db.session.commit()
        receipt.update_warehouse_item_skus()
        db.session.commit()

        flash("入库成功。", "success")
        return redirect(url_for("index"))

    return render_template("stockin.html.jinja", form=form, items=items)

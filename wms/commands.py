from wms import app, db
from wms.settings import sync_initial_reference_data
from wms.models import (
    Receipt,
    User,
    Item,
    ItemSKU,
    Transaction,
    ReceiptType,
)
import click


@app.cli.command()
@click.option("--drop", is_flag=True, help="Create after drop.")
def initdb(drop):
    if drop:
        db.drop_all()
    db.create_all()
    click.echo("Initialized database.")
    sync_initial_reference_data()
    click.echo("User creating done.")


@app.cli.command()
def forge():
    user: User = db.session.execute(
        db.select(User).filter_by(username=app.config["INITIAL_ADMIN_USERNAME"])
    ).scalar_one()
    # add transaction test item
    item = Item(name="螺丝")
    db.session.add(item)
    # add a transaction containing skus
    itemSKU = ItemSKU(item=item, brand="特斯拉", spec="100颗/袋")
    db.session.add(itemSKU)
    receipt = Receipt(
        operator=user,
        refcode="20250214-1",
        warehouse=user.warehouse,
        type=ReceiptType.STOCKIN,
    )
    transaction = Transaction(itemSKU=itemSKU, count=5, price=10, receipt=receipt)
    db.session.add(transaction)
    transaction = Transaction(itemSKU=itemSKU, count=2, price=5, receipt=receipt)
    db.session.add(transaction)
    db.session.add(receipt)
    db.session.commit()
    receipt.update_warehouse_item_skus()
    db.session.commit()

    # add display test item
    receipt = Receipt(
        operator=user,
        refcode="20250214-2",
        warehouse=user.warehouse,
        type=ReceiptType.STOCKIN,
    )
    item = Item(name="占位产品1")
    db.session.add(item)
    for i in range(1, 20):
        itemSKU = ItemSKU(item=item, brand="占位", spec=f"规格{i}")
        db.session.add(itemSKU)
        db.session.add(Transaction(itemSKU=itemSKU, count=i, price=i, receipt=receipt))
    for i in range(2, 50):
        item = Item(name=f"占位产品{i}")
        db.session.add(item)
        itemSKU = ItemSKU(item=item, brand="假冒伪劣", spec=f"规格{i}")
        db.session.add(itemSKU)
        db.session.add(Transaction(itemSKU=itemSKU, count=i, price=i, receipt=receipt))
    db.session.add(receipt)
    db.session.commit()
    receipt.update_warehouse_item_skus()
    db.session.commit()

    user: User = db.session.execute(
        db.select(User).filter_by(username=app.config["INITIAL_ADMIN_USERNAME"])
    ).scalar_one()
    item: Item = db.session.execute(db.select(Item).filter_by(name="螺丝")).scalar_one()
    itemSKU: ItemSKU = db.session.execute(
        db.select(ItemSKU).filter_by(item=item)
    ).scalar_one()
    receipt = Receipt(
        operator=user,
        refcode="20250214-3",
        warehouse=user.warehouse,
        type=ReceiptType.STOCKIN,
    )
    db.session.add(receipt)
    db.session.add(Transaction(itemSKU=itemSKU, count=5, price=10, receipt=receipt))
    db.session.commit()
    receipt.update_warehouse_item_skus()
    db.session.commit()

    click.echo("Data forging done.")

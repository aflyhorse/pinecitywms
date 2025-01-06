from wms import app, db
from wms.models import User, Item, ItemSKU, Stock
import click


@app.cli.command()
@click.option("--drop", is_flag=True, help="Create after drop.")
def initdb(drop):
    if drop:
        db.drop_all()
    db.create_all()
    click.echo("Initialized database.")

    usernames = [("admin", "管理员"), ("ruodian", "弱电")]
    for name in usernames:
        user = User(username=name[0], nickname=name[1], is_admin=True)
        user.set_password(name[0])
        db.session.add(user)

    usernames = [
        ("qiangdian", "强电"),
        ("kongtiao", "空调"),
        ("guolu", "锅炉"),
        ("jianxiu", "检修"),
        ("huishou", "回收"),
    ]
    for name in usernames:
        user = User(username=name[0], nickname=name[1], is_admin=False)
        user.set_password(name[0])
        db.session.add(user)

    user_huishou: User = db.session.execute(
        db.select(User).filter_by(username="huishou")
    ).scalar_one()
    user_huishou.active = False

    db.session.commit()
    click.echo("User creating done.")


@app.cli.command()
def forge():
    user: User = db.session.execute(
        db.select(User).filter_by(username="jianxiu")
    ).scalar_one()
    item = Item(name="螺丝")
    db.session.add(item)
    itemSKU = ItemSKU(item=item, brand="特斯拉", spec="100颗/袋")
    db.session.add(itemSKU)
    stock = Stock(itemSKU=itemSKU, count=5, price=10, owner=user)
    db.session.add(stock)
    itemSKU = ItemSKU(item=item, brand="宝马", spec="200颗/袋")
    db.session.add(itemSKU)
    stock = Stock(itemSKU=itemSKU, count=2, price=5, owner=user)
    db.session.add(stock)
    for i in range(1, 300):
        item = Item(name="占位产品" + str(i))
        db.session.add(item)
        itemSKU = ItemSKU(item=item, brand="假冒伪劣", spec="产品" + str(i))
        db.session.add(itemSKU)
    db.session.commit()
    click.echo("Data forging done.")

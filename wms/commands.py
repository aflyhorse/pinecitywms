from wms import app, db
from wms.models import User
import click


@app.cli.command()
@click.option("--drop", is_flag=True, help="Create after drop.")
def initdb(drop):
    if drop:
        db.drop_all()
    db.create_all()
    click.echo("Initialized database.")

    usernames = ["admin", "ruodian", "qiangdian", "kongtiao", "guolu", "jianxiu"]
    for name in usernames:
        user = User(username=name)
        user.set_password(name)
        db.session.add(user)
    db.session.commit()
    click.echo("Data Injection done.")

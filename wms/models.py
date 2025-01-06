from wms import db
from flask_login import UserMixin
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from typing import List
from datetime import datetime


class User(db.Model, UserMixin):
    username: Mapped[str] = mapped_column(
        db.String(20), unique=True, nullable=False, index=True
    )
    nickname: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(162))
    is_admin: Mapped[bool]
    active: Mapped[bool] = mapped_column(default=True)
    stocks: Mapped[List["Stock"]] = relationship(back_populates="owner")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def validate_password(self, password: str):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active


class Item(db.Model):
    name: Mapped[str] = mapped_column(
        db.String(30), unique=True, nullable=False, index=True
    )
    skus: Mapped[List["ItemSKU"]] = relationship(back_populates="item")


class ItemSKU(db.Model):
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    item: Mapped[Item] = relationship(back_populates="skus")
    brand: Mapped[str] = mapped_column(db.String(30))
    spec: Mapped[str] = mapped_column(db.String(50))
    stocks: Mapped[List["Stock"]] = relationship(back_populates="itemSKU")


class Stock(db.Model):
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"))
    itemSKU: Mapped[ItemSKU] = relationship(back_populates="stocks")
    count: Mapped[int]
    price: Mapped[float]
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    owner: Mapped[User] = relationship(back_populates="stocks")
    date: Mapped[datetime] = mapped_column(default=datetime.now)

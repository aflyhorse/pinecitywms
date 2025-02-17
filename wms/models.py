from wms import db
from flask_login import UserMixin
from sqlalchemy import ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from typing import List
from datetime import datetime
import enum


class User(db.Model, UserMixin):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        db.String(20), unique=True, nullable=False, index=True
    )
    nickname: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(162))
    is_admin: Mapped[bool]
    receipts: Mapped[List["Receipt"]] = relationship(back_populates="operator")
    warehouse: Mapped["Warehouse"] = relationship(back_populates="owner", uselist=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def validate_password(self, password: str):
        return check_password_hash(self.password_hash, password)


class Item(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        db.String(30), unique=True, nullable=False, index=True
    )
    skus: Mapped[List["ItemSKU"]] = relationship(back_populates="item")


class Warehouse(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    owner: Mapped[User] = relationship(back_populates="warehouse", uselist=False)
    receipts: Mapped[List["Receipt"]] = relationship(back_populates="warehouse")
    item_skus: Mapped[List["WarehouseItemSKU"]] = relationship(
        "WarehouseItemSKU", back_populates="warehouse"
    )


class ItemSKU(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    item: Mapped[Item] = relationship(back_populates="skus")
    brand: Mapped[str] = mapped_column(db.String(30))
    spec: Mapped[str] = mapped_column(db.String(50))
    trasanctions: Mapped[List["Transaction"]] = relationship(back_populates="itemSKU")
    warehouses: Mapped[List["WarehouseItemSKU"]] = relationship(
        "WarehouseItemSKU", back_populates="itemSKU"
    )


class WarehouseItemSKU(db.Model):
    __tablename__ = "warehouse_item_sku"
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), primary_key=True
    )
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"), primary_key=True)
    count: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    average_price: Mapped[float] = mapped_column(db.Float, default=0.0, nullable=False)
    warehouse: Mapped[Warehouse] = relationship("Warehouse", back_populates="item_skus")
    itemSKU: Mapped[ItemSKU] = relationship("ItemSKU", back_populates="warehouses")


class Transaction(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"))
    itemSKU: Mapped[ItemSKU] = relationship(back_populates="trasanctions")
    count: Mapped[int]
    price: Mapped[float]
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), nullable=False)
    receipt: Mapped["Receipt"] = relationship(back_populates="transactions")


class ReceiptType(enum.Enum):
    STOCKIN = 0
    STOCKOUT = 1
    TAKESTOCK = 2


class Receipt(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    refcode: Mapped[str] = mapped_column(db.String(30))
    type: Mapped[ReceiptType] = mapped_column(
        Enum(ReceiptType), default=ReceiptType.STOCKOUT, nullable=False
    )
    operator_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    operator: Mapped[User] = relationship(back_populates="receipts")
    transactions: Mapped[List[Transaction]] = relationship(back_populates="receipt")
    date: Mapped[datetime] = mapped_column(default=datetime.now, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), nullable=False
    )
    warehouse: Mapped[Warehouse] = relationship(back_populates="receipts")

    @property
    def sum(self) -> float:
        return sum(
            transaction.count * transaction.price for transaction in self.transactions
        )

    # should instantly call this function after commit, to update warehouse item skus
    def update_warehouse_item_skus(self):
        for transaction in self.transactions:
            warehouse_item_sku = (
                db.session.query(WarehouseItemSKU)
                .filter_by(
                    warehouse_id=self.warehouse_id, itemSKU_id=transaction.itemSKU_id
                )
                .first()
            )
            if warehouse_item_sku:
                if self.type == ReceiptType.STOCKIN:
                    total_count = warehouse_item_sku.count + transaction.count
                    warehouse_item_sku.average_price = (
                        warehouse_item_sku.count * warehouse_item_sku.average_price
                        + transaction.count * transaction.price
                    ) / total_count
                    warehouse_item_sku.count = total_count
                elif (
                    self.type == ReceiptType.STOCKOUT
                    or self.type == ReceiptType.TAKESTOCK
                ):
                    warehouse_item_sku.count += transaction.count
            else:
                warehouse_item_sku = WarehouseItemSKU(
                    warehouse_id=self.warehouse_id,
                    itemSKU_id=transaction.itemSKU_id,
                    count=transaction.count,
                    average_price=transaction.price,
                )
                db.session.add(warehouse_item_sku)
        db.session.commit()

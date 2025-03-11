from wms import db
from flask_login import UserMixin
from sqlalchemy import ForeignKey, Enum
from sqlalchemy.types import String, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from typing import List
from datetime import datetime
from decimal import Decimal
import enum


class User(db.Model, UserMixin):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    nickname: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(162))
    is_admin: Mapped[bool]
    receipts: Mapped[List["Receipt"]] = relationship(back_populates="operator")
    warehouse: Mapped["Warehouse"] = relationship(back_populates="owner", uselist=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def validate_password(self, password: str):
        return check_password_hash(self.password_hash, password)


class Item(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Basic item information
    name: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    # One item can have multiple SKUs with different specs
    skus: Mapped[List["ItemSKU"]] = relationship(back_populates="item")


class Warehouse(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # Public warehouses are visible to all users
    is_public: Mapped[bool] = mapped_column(default=False)
    # Private warehouses have an owner
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    owner: Mapped[User] = relationship(back_populates="warehouse", uselist=False)
    # Related receipts and inventory items
    receipts: Mapped[List["Receipt"]] = relationship(back_populates="warehouse")
    item_skus: Mapped[List["WarehouseItemSKU"]] = relationship(
        "WarehouseItemSKU", back_populates="warehouse"
    )


class ItemSKU(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Link to parent item
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    item: Mapped[Item] = relationship(back_populates="skus")
    # SKU specific details
    brand: Mapped[str] = mapped_column(String(30))
    spec: Mapped[str] = mapped_column(String(50))
    # Related transactions and warehouse inventory
    trasanctions: Mapped[List["Transaction"]] = relationship(back_populates="itemSKU")
    warehouses: Mapped[List["WarehouseItemSKU"]] = relationship(
        "WarehouseItemSKU", back_populates="itemSKU"
    )


class WarehouseItemSKU(db.Model):
    __tablename__ = "warehouse_item_sku"
    # Composite primary key of warehouse and SKU
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), primary_key=True
    )
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"), primary_key=True)
    # Current inventory status
    count: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)
    average_price: Mapped[float] = mapped_column(default=0, nullable=False)
    # Relationships
    warehouse: Mapped[Warehouse] = relationship("Warehouse", back_populates="item_skus")
    itemSKU: Mapped[ItemSKU] = relationship("ItemSKU", back_populates="warehouses")


class Transaction(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Link to the SKU being transacted
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"))
    itemSKU: Mapped[ItemSKU] = relationship(back_populates="trasanctions")
    # Transaction details
    count: Mapped[int]
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Link to the receipt this transaction belongs to
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), nullable=False)
    receipt: Mapped["Receipt"] = relationship(back_populates="transactions")


class ReceiptType(enum.Enum):
    STOCKIN = 0  # Incoming stock
    STOCKOUT = 1  # Outgoing stock
    TAKESTOCK = 2  # Stock taking/adjustment


class Receipt(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Receipt identification
    refcode: Mapped[str] = mapped_column(String(30), unique=True, nullable=True)
    type: Mapped[ReceiptType] = mapped_column(
        Enum(ReceiptType), default=ReceiptType.STOCKOUT, nullable=False
    )
    # Receipt operator and timestamp
    operator_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    operator: Mapped[User] = relationship(back_populates="receipts")
    date: Mapped[datetime] = mapped_column(default=datetime.now, nullable=False)
    # Related items and warehouse
    transactions: Mapped[List[Transaction]] = relationship(back_populates="receipt")
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id"), nullable=False
    )
    warehouse: Mapped[Warehouse] = relationship(back_populates="receipts")
    # Area and Department for stockout receipts
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"), nullable=True)
    area: Mapped["Area"] = relationship("Area")
    department_id: Mapped[int] = mapped_column(
        ForeignKey("department.id"), nullable=True
    )
    department: Mapped["Department"] = relationship("Department")
    # Specific location for stockout
    location: Mapped[str] = mapped_column(String(30), nullable=True)

    @property
    def sum(self) -> Decimal:
        # Calculate total value of the receipt using Decimal arithmetic
        return sum(
            Decimal(str(transaction.count)) * transaction.price
            for transaction in self.transactions
        )

    def update_warehouse_item_skus(self):
        # Update warehouse inventory after a receipt is processed
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
                    # Update average price and count for stock in
                    total_count = warehouse_item_sku.count + transaction.count
                    # Convert counts to Decimal for precise arithmetic
                    dec_total_count = Decimal(str(total_count))
                    dec_wh_count = Decimal(str(warehouse_item_sku.count))
                    dec_trans_count = Decimal(str(transaction.count))

                    warehouse_item_sku.average_price = (
                        dec_wh_count * Decimal(str(warehouse_item_sku.average_price))
                        + dec_trans_count * transaction.price
                    ) / dec_total_count
                    warehouse_item_sku.count = total_count
                elif (
                    self.type == ReceiptType.STOCKOUT
                    or self.type == ReceiptType.TAKESTOCK
                ):
                    # Update count for stock out or stock taking
                    warehouse_item_sku.count += transaction.count
            else:
                # Create new warehouse item SKU if it doesn't exist
                warehouse_item_sku = WarehouseItemSKU(
                    warehouse_id=self.warehouse_id,
                    itemSKU_id=transaction.itemSKU_id,
                    count=transaction.count,
                    average_price=float(
                        transaction.price
                    ),  # Convert to float for storage
                )
                db.session.add(warehouse_item_sku)
        db.session.commit()


class Area(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class Department(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)

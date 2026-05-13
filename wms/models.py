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
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_auditor: Mapped[bool] = mapped_column(default=False, nullable=False)
    receipts: Mapped[List["Receipt"]] = relationship(
        back_populates="operator", foreign_keys="Receipt.operator_id"
    )
    warehouse: Mapped["Warehouse"] = relationship(back_populates="owner", uselist=False)
    employees: Mapped[List["Employee"]] = relationship(back_populates="user")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def validate_password(self, password: str):
        return check_password_hash(self.password_hash, password)

    @property
    def can_view_all_warehouses(self) -> bool:
        return self.is_admin or self.is_auditor

    @property
    def can_view_all_tool_groups(self) -> bool:
        return self.is_admin or self.is_auditor

    @property
    def can_operate_inventory(self) -> bool:
        return not self.is_auditor

    @property
    def can_manage_employees(self) -> bool:
        return not self.is_auditor

    @property
    def can_generate_scrap_confirmation(self) -> bool:
        return self.is_admin or self.is_auditor


class Item(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Basic item information
    name: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    # Whether this item is a tool (managed via tool inventory)
    is_tool: Mapped[bool] = mapped_column(default=False, nullable=False)
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
    # Whether this SKU is disabled/deprecated
    disabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Related transactions and warehouse inventory
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="itemSKU"
    )
    warehouses: Mapped[List["WarehouseItemSKU"]] = relationship(
        "WarehouseItemSKU", back_populates="itemSKU"
    )
    # Tool inventory entries (one per group-user per SKU, exist only if item.is_tool)
    tool_inventories: Mapped[List["ToolInventory"]] = relationship(
        "ToolInventory", back_populates="itemSKU"
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
    itemSKU: Mapped[ItemSKU] = relationship(back_populates="transactions")
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
    # Whether this receipt is revoked
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)
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
    # Additional notes for stockout and takestock
    note: Mapped[str] = mapped_column(String(100), nullable=True)
    # Whether this receipt involves tool items
    is_tool: Mapped[bool] = mapped_column(default=False, nullable=False)

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
            # Attempt to lock the warehouse_item_sku row to prevent concurrent updates
            warehouse_item_sku = (
                db.session.query(WarehouseItemSKU)
                .with_for_update()
                .filter_by(
                    warehouse_id=self.warehouse_id, itemSKU_id=transaction.itemSKU_id
                )
                .first()
            )
            # Fetch related SKU and warehouse once to avoid duplicate queries
            item_sku = db.session.get(ItemSKU, transaction.itemSKU_id)
            warehouse_obj = db.session.get(Warehouse, self.warehouse_id)
            if warehouse_item_sku:
                if self.type == ReceiptType.STOCKIN:
                    # Initialize average price if it's not set
                    if warehouse_item_sku.average_price is None or Decimal(
                        str(warehouse_item_sku.average_price)
                    ) == Decimal("0.00"):
                        warehouse_item_sku.average_price = float(transaction.price)
                    # Update average price and count for stock in using Decimal
                    total_count = warehouse_item_sku.count + transaction.count
                    if total_count != 0:
                        dec_total_count = Decimal(str(total_count))
                        dec_wh_count = Decimal(str(warehouse_item_sku.count))
                        dec_trans_count = Decimal(str(transaction.count))
                        dec_wh_price = Decimal(str(warehouse_item_sku.average_price))
                        dec_result = (
                            dec_wh_count * dec_wh_price
                            + dec_trans_count * transaction.price
                        ) / dec_total_count
                        # store as float for compatibility
                        warehouse_item_sku.average_price = float(dec_result)
                    else:
                        warehouse_item_sku.average_price = 0
                    warehouse_item_sku.count = total_count
                elif (
                    self.type == ReceiptType.STOCKOUT
                    or self.type == ReceiptType.TAKESTOCK
                ):
                    # Check if this would cause negative inventory
                    new_count = warehouse_item_sku.count + transaction.count
                    if new_count < 0:
                        item_name = (
                            item_sku.item.name
                            if item_sku and item_sku.item
                            else "Unknown"
                        )
                        brand = item_sku.brand if item_sku else ""
                        spec = item_sku.spec if item_sku else ""
                        warehouse_name = (
                            warehouse_obj.name if warehouse_obj else "Unknown"
                        )
                        raise ValueError(
                            f"库存不足: {item_name} {brand} {spec} 在 {warehouse_name} 仓库中库存为 {warehouse_item_sku.count}, "
                            f"无法扣减 {abs(transaction.count)} 件"
                        )
                    # Update count for stock out or stock taking
                    warehouse_item_sku.count = new_count
            else:
                # For new items, only allow STOCKIN or positive adjustments
                if self.type == ReceiptType.STOCKOUT or (
                    self.type == ReceiptType.TAKESTOCK and transaction.count < 0
                ):
                    item_name = (
                        item_sku.item.name if item_sku and item_sku.item else "Unknown"
                    )
                    brand = item_sku.brand if item_sku else ""
                    spec = item_sku.spec if item_sku else ""
                    warehouse_name = warehouse_obj.name if warehouse_obj else "Unknown"
                    raise ValueError(
                        f"物品不存在于仓库: {item_name} {brand} {spec} 不在 {warehouse_name} 仓库中"
                    )

                # Create new warehouse item SKU if it doesn't exist
                warehouse_item_sku = WarehouseItemSKU(
                    warehouse_id=self.warehouse_id,
                    itemSKU_id=transaction.itemSKU_id,
                    count=transaction.count,
                    average_price=float(transaction.price),
                )
                db.session.add(warehouse_item_sku)
        db.session.commit()


class Area(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class Department(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class Employee(db.Model):
    """Represents a worker/employee associated with a shift group (班组 user)."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    is_resigned: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Associated 班组 user account
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    user: Mapped["User"] = relationship("User", back_populates="employees")
    # Tool holdings and records
    tool_holdings: Mapped[List["EmployeeToolHolding"]] = relationship(
        back_populates="employee"
    )
    tool_transactions: Mapped[List["ToolTransaction"]] = relationship(
        back_populates="employee"
    )


class ToolInventory(db.Model):
    """Tracks per-group tool quantities and pending-scrap count for each tool SKU."""

    # Composite PK: one row per (group user, SKU)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"), primary_key=True)
    user: Mapped["User"] = relationship("User")
    itemSKU: Mapped["ItemSKU"] = relationship(
        "ItemSKU", back_populates="tool_inventories"
    )
    # Current available stock (余量)
    count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Pending scrap quantity (待报废数量)
    pending_scrap: Mapped[int] = mapped_column(default=0, nullable=False)


class EmployeeToolHolding(db.Model):
    """Tracks how many of each tool SKU an employee is currently holding."""

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employee.id"), primary_key=True
    )
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"), primary_key=True)
    count: Mapped[int] = mapped_column(default=0, nullable=False)
    employee: Mapped["Employee"] = relationship(back_populates="tool_holdings")
    itemSKU: Mapped["ItemSKU"] = relationship("ItemSKU")


class ToolReceiptType(enum.Enum):
    REQUISITION = 0  # 领用
    EXCHANGE = 1  # 更换
    RETURN = 2  # 归还
    SCRAP = 3  # 报废


class ToolReceipt(db.Model):
    """A batch tool operation (requisition / exchange / return / scrap)."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[ToolReceiptType] = mapped_column(Enum(ToolReceiptType), nullable=False)
    # Employee who is receiving / returning the tools (null for scrap)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), nullable=True)
    employee: Mapped["Employee"] = relationship("Employee")
    # Target user for scrap confirmations (the group whose tools were scrapped)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    target_user: Mapped["User"] = relationship("User", foreign_keys=[target_user_id])
    # Staff member who performed the operation
    operator_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    operator: Mapped["User"] = relationship("User", foreign_keys=[operator_id])
    # Auditor/admin who confirmed a scrap request
    confirmed_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=True)
    confirmed_by: Mapped["User"] = relationship("User", foreign_keys=[confirmed_by_id])
    confirmed_at: Mapped[datetime] = mapped_column(nullable=True)
    date: Mapped[datetime] = mapped_column(default=datetime.now, nullable=False)
    # Whether this confirmation slip has been printed
    printed: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Linked stockout receipt generated for scrap operations
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipt.id"), nullable=True)
    receipt: Mapped["Receipt"] = relationship("Receipt")
    # Individual tool lines
    transactions: Mapped[List["ToolTransaction"]] = relationship(
        back_populates="tool_receipt"
    )


class ToolTransaction(db.Model):
    """One line in a ToolReceipt: which SKU and how many."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tool_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("tool_receipt.id"), nullable=False
    )
    tool_receipt: Mapped["ToolReceipt"] = relationship(back_populates="transactions")
    itemSKU_id: Mapped[int] = mapped_column(ForeignKey("item_sku.id"), nullable=False)
    itemSKU: Mapped["ItemSKU"] = relationship("ItemSKU")
    count: Mapped[int] = mapped_column(nullable=False)
    # Employee who is receiving / returning the tools (null for scrap)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employee.id"), nullable=True)
    employee: Mapped["Employee"] = relationship(back_populates="tool_transactions")

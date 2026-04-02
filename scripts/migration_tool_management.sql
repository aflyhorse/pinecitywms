-- Migration: Add tool management features
-- Date: 2026-02-26
-- Column names match SQLAlchemy's default (attribute name used as-is).

-- 1. Add is_tool flag to item table
ALTER TABLE item ADD COLUMN is_tool BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Add is_tool flag to receipt table
ALTER TABLE receipt ADD COLUMN is_tool BOOLEAN NOT NULL DEFAULT FALSE;

-- 3. Create employee table (maps to Employee model)
CREATE TABLE employee (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(30) NOT NULL,
    is_resigned BOOLEAN NOT NULL DEFAULT FALSE,
    user_id INTEGER REFERENCES user(id)
);
CREATE INDEX ix_employee_employee_id ON employee (employee_id);

-- 4. Create tool_inventory table (maps to ToolInventory model)
-- Composite PK: one row per (group user, SKU)
CREATE TABLE tool_inventory (
    user_id INTEGER NOT NULL REFERENCES user(id),
    "itemSKU_id" INTEGER NOT NULL REFERENCES item_sku(id),
    count INTEGER NOT NULL DEFAULT 0,
    pending_scrap INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, "itemSKU_id")
);

-- 5. Create employee_tool_holding table (maps to EmployeeToolHolding model)
CREATE TABLE employee_tool_holding (
    employee_id INTEGER NOT NULL REFERENCES employee(id),
    "itemSKU_id" INTEGER NOT NULL REFERENCES item_sku(id),
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_id, "itemSKU_id")
);

-- 6. Create tool_receipt table (maps to ToolReceipt model)
CREATE TABLE tool_receipt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type VARCHAR(11) NOT NULL,
    employee_id INTEGER REFERENCES employee(id),
    operator_id INTEGER NOT NULL REFERENCES user(id),
    date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    printed BOOLEAN NOT NULL DEFAULT FALSE,
    receipt_id INTEGER REFERENCES receipt(id)
);

-- 7. Create tool_transaction table (maps to ToolTransaction model)
CREATE TABLE tool_transaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_receipt_id INTEGER NOT NULL REFERENCES tool_receipt(id),
    "itemSKU_id" INTEGER NOT NULL REFERENCES item_sku(id),
    count INTEGER NOT NULL,
    employee_id INTEGER REFERENCES employee(id)
);

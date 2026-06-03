import json
import re

import pytest
from wms.models import (
    Area,
    Department,
    Warehouse,
    Item,
    ItemSKU,
    WarehouseItemSKU,
    ToolInventory,
    User,
    Receipt,
    ReceiptType,
    Transaction,
)
from wms import app, db
from werkzeug.security import generate_password_hash


def _sku_display(sku):
    return f"{sku.item.name} - {sku.brand} - {sku.spec}"


@pytest.mark.usefixtures("test_item")
def test_stockin(auth_client, test_warehouse):
    # Test stockin page access
    response = auth_client.get("/stockin")
    assert response.status_code == 200

    # Get test item SKU
    with app.app_context():
        sku = ItemSKU.query.first()

    # Test stockin submission
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "10",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "入库成功".encode() in response.data

    # Verify the warehouse item count
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        warehouse_item = warehouse.item_skus[0]
        assert warehouse_item.count == 10
        assert warehouse_item.average_price == 100.00


def test_tool_stockin_uses_warehouse_owner(auth_client):
    with app.app_context():
        owner = User(username="warehouse_owner", nickname="仓库归属人", is_admin=False)
        owner.set_password("password123")
        db.session.add(owner)
        db.session.flush()

        item = Item(name="归属测试工具", is_tool=True)
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="Brand", spec="Spec")
        db.session.add(sku)
        db.session.flush()

        warehouse = Warehouse(name="归属测试仓库", owner_id=owner.id)
        db.session.add(warehouse)
        db.session.commit()

        warehouse_id = warehouse.id
        sku_id = sku.id

    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TOOL-STOCKIN-001",
            "warehouse": warehouse_id,
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "4",
            "items-0-price": "12.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "入库成功".encode() in response.data


def test_stockout_autoselects_single_area_and_department(auth_client, test_warehouse):
    with app.app_context():
        area = Area(name="单一区域")
        department = Department(name="单一部门")
        db.session.add_all([area, department])
        db.session.commit()
        area_id = area.id
        department_id = department.id

    response = auth_client.get("/stockout")
    assert response.status_code == 200

    area_pattern = (
        rb'<option[^>]*(?:selected[^>]*value="%d"|value="%d"[^>]*selected)'
        % (
            area_id,
            area_id,
        )
    )
    department_pattern = (
        rb'<option[^>]*(?:selected[^>]*value="%d"|value="%d"[^>]*selected)'
        % (
            department_id,
            department_id,
        )
    )
    assert re.search(area_pattern, response.data)
    assert re.search(department_pattern, response.data)


def test_admin_stockin_then_toggle_tool_targets_user_warehouse_and_tool_group(
    auth_client, regular_warehouse
):
    with app.app_context():
        owner = db.session.execute(
            db.select(User).filter_by(username="testuser")
        ).scalar_one()
        item = Item(name="管理员入库联动测试", is_tool=False)
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="联动品牌", spec="联动规格")
        db.session.add(sku)
        db.session.commit()

        item_id = item.id
        sku_id = sku.id
        owner_id = owner.id

    stockin_resp = auth_client.post(
        "/stockin",
        data={
            "refcode": "ADMIN-TO-USER-WH-001",
            "warehouse": regular_warehouse,
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "7",
            "items-0-price": "21.00",
        },
        follow_redirects=True,
    )
    assert stockin_resp.status_code == 200
    assert "入库成功".encode() in stockin_resp.data

    toggle_resp = auth_client.post(f"/item/{item_id}/toggle_tool")
    assert toggle_resp.status_code == 200
    toggle_data = json.loads(toggle_resp.data)
    assert toggle_data["success"] is True
    assert toggle_data["is_tool"] is True
    assert "已标记为工具" in toggle_data["message"]

    with app.app_context():
        warehouse_item = WarehouseItemSKU.query.filter_by(
            warehouse_id=regular_warehouse, itemSKU_id=sku_id
        ).first()
        assert warehouse_item is not None
        assert warehouse_item.count == 7

        tool_row = ToolInventory.query.filter_by(
            user_id=owner_id, itemSKU_id=sku_id
        ).first()
        assert tool_row is not None
        assert tool_row.count == 7

        wrong_tool_row = ToolInventory.query.filter_by(
            user_id=db.session.execute(
                db.select(User.id).filter_by(username="testadmin")
            ).scalar_one(),
            itemSKU_id=sku_id,
        ).first()
        assert wrong_tool_row is None


def test_stockin_validation(auth_client, test_warehouse):
    # Test invalid item ID
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": "99999",  # Non-existent ID
            "items-0-quantity": "10",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "无效的物品".encode() in response.data


def test_non_admin_stockin_access(client, regular_user):
    # Login as non-admin user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to stockin
    response = client.get("/stockin", follow_redirects=True)
    assert response.status_code == 200
    assert b"Unauthorized Access" in response.data


def test_stockout_page_access(auth_client):
    # Test stockout page access
    response = auth_client.get("/stockout")
    assert response.status_code == 200
    assert b"warehouse" in response.data  # Check for warehouse field
    assert b"area" in response.data  # Check for area field
    assert b"department" in response.data  # Check for department field
    assert b"location" in response.data  # Check for location field


def test_stockout_page_excludes_tool_items_and_rejects_tool_stockout(
    auth_client, test_warehouse, test_customer
):
    with app.app_context():
        tool_item = Item(name="出库过滤工具", is_tool=True)
        regular_item = Item(name="出库过滤普通品", is_tool=False)
        db.session.add_all([tool_item, regular_item])
        db.session.flush()

        tool_sku = ItemSKU(item=tool_item, brand="工具品牌", spec="工具规格")
        regular_sku = ItemSKU(item=regular_item, brand="普通品牌", spec="普通规格")
        db.session.add_all([tool_sku, regular_sku])
        db.session.flush()

        db.session.add(
            WarehouseItemSKU(
                warehouse_id=test_warehouse,
                itemSKU_id=tool_sku.id,
                count=3,
                average_price=10,
            )
        )
        db.session.add(
            WarehouseItemSKU(
                warehouse_id=test_warehouse,
                itemSKU_id=regular_sku.id,
                count=5,
                average_price=20,
            )
        )
        db.session.commit()

        tool_display = f"{tool_item.name} - {tool_sku.brand} - {tool_sku.spec}"
        regular_display = (
            f"{regular_item.name} - {regular_sku.brand} - {regular_sku.spec}"
        )

    page_resp = auth_client.get(f"/stockout?warehouse={test_warehouse}")
    assert page_resp.status_code == 200
    assert regular_display.encode() in page_resp.data
    assert tool_display.encode() not in page_resp.data

    post_resp = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": tool_display,
            "items-0-item_sku_id": str(tool_sku.id),
            "items-0-quantity": "1",
            "items-0-price": "10.00",
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert "工具物品不能直接出库".encode() in post_resp.data


def test_area_department_selection(auth_client, test_customer):
    # Test area and department selection functionality
    response = auth_client.post(
        "/stockout", data={"area": test_customer["area"]}, follow_redirects=True
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("test_item")
def test_stockout_process(auth_client, test_warehouse, test_customer):
    # First add some inventory via stockin
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_display = _sku_display(sku)

    # Add inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "STOCKOUT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "20",
            "items-0-price": "50.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now attempt to stockout
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

    # Verify the inventory was reduced
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        warehouse_item = warehouse.item_skus[0]
        assert warehouse_item.count == 15  # 20 - 5 = 15


@pytest.mark.usefixtures("test_item")
def test_stockout_insufficient_stock(auth_client, test_warehouse, test_customer):
    # First add some inventory via stockin
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_display = _sku_display(sku)

    # Add limited inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "STOCKOUT-TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "3",
            "items-0-price": "50.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now attempt to stockout more than available
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku.id),
            "items-0-quantity": "10",  # More than available
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "库存不足".encode() in response.data


def test_stockout_invalid_item(auth_client, test_customer, test_warehouse):
    # Test with an invalid item ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": "不存在的物品",
            "items-0-item_sku_id": "99999",  # Non-existent ID
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Invalid item ID".encode() in response.data


def test_inventory(auth_client, test_warehouse, test_item):
    # Test inventory page access
    response = auth_client.get("/inventory")
    assert response.status_code == 200

    # Add some inventory to test with
    sku = ItemSKU.query.first()
    # First add some stock via stockin
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "INV-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "50",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Test inventory view with search parameters
    response = auth_client.post(
        "/inventory",
        data={
            "name": sku.item.name,
            "brand": sku.brand,
            "spec": sku.spec,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert sku.item.name.encode() in response.data
    assert sku.brand.encode() in response.data
    assert sku.spec.encode() in response.data
    assert b"50" in response.data  # Check quantity is shown

    # Test warehouse selection
    response = auth_client.get(f"/inventory?warehouse={test_warehouse}")
    assert response.status_code == 200


@pytest.mark.usefixtures("test_item")
def test_quick_stockout_button(auth_client, test_warehouse):
    """Test the quick stockout button in the inventory page"""
    # Get the item details and ID within the app context
    with app.app_context():
        sku = ItemSKU.query.first()
        item_name = sku.item.name
        brand = sku.brand
        spec = sku.spec
        sku_id = sku.id
        # Generate the expected display name that will be shown in the form
        expected_item_text = f"{item_name} - {brand} - {spec}"

    # Add inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "QUICK-OUT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "30",
            "items-0-price": "80.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Access inventory page to verify the quick stockout button exists
    response = auth_client.get(f"/inventory?warehouse={test_warehouse}")
    assert response.status_code == 200
    assert "快捷出库".encode() in response.data

    # Get the stockout page with the item_id parameter (simulating clicking the quick stockout button)
    response = auth_client.get(f"/stockout?warehouse={test_warehouse}&item_id={sku_id}")
    assert response.status_code == 200

    # Verify that the form has been pre-filled with the selected item
    assert expected_item_text.encode() in response.data

    # Check for form field values (can't directly check hidden fields, but can check visible elements)
    html_content = response.data.decode("utf-8")
    assert (
        f'value="{expected_item_text}"' in html_content
    )  # Check item name is pre-filled
    assert 'value="1"' in html_content  # Check the default quantity is 1


@pytest.mark.usefixtures("test_item")
def test_quick_stockout_complete_flow(auth_client, test_warehouse, test_customer):
    """Test the complete flow from quick stockout button to completed stockout"""
    # Get the item details and ID within the app context
    initial_count = 40

    with app.app_context():
        sku = ItemSKU.query.first()
        item_name = sku.item.name
        brand = sku.brand
        spec = sku.spec
        sku_id = sku.id
        # Generate the expected display name that will be shown in the form
        expected_item_text = f"{item_name} - {brand} - {spec}"

    # Add inventory
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "QUICK-OUT-FLOW-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku_id),
            "items-0-quantity": str(initial_count),
            "items-0-price": "90.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Simulate clicking the quick stockout button by visiting the stockout page with item_id
    response = auth_client.get(f"/stockout?warehouse={test_warehouse}&item_id={sku_id}")
    assert response.status_code == 200

    # Now submit the stockout form with the pre-filled item
    # We'll use 5 as the quantity to stockout
    stockout_quantity = 5
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "快捷出库测试位置",
            "items-0-item_id": expected_item_text,  # Use the display text
            "items-0-item_sku_id": str(sku_id),  # The hidden field with actual ID
            "items-0-quantity": str(stockout_quantity),
            "items-0-price": "90.00",  # Use same price as stock in
            "items-0-stock_count": str(initial_count),  # Current stock count
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

    # Verify inventory was reduced
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        warehouse_item = next(
            (item for item in warehouse.item_skus if item.itemSKU_id == sku_id), None
        )
        assert warehouse_item is not None
        assert warehouse_item.count == initial_count - stockout_quantity


def test_inventory_access_control(client, regular_user, regular_warehouse):
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to inventory
    response = client.get("/inventory")
    assert response.status_code == 200

    # Create another user and their warehouse
    otherwarehouse_id = None
    otherwarehouse_name = "Other Warehouse"
    with app.app_context():
        other_user = User(
            username="otherwarehouse",
            nickname="Other Warehouse Owner",
            password_hash=generate_password_hash("password123"),
            is_admin=False,
        )
        db.session.add(other_user)
        db.session.flush()  # Flush to get the user ID

        # Create warehouse owned by the other user
        otherwarehouse = Warehouse(name=otherwarehouse_name, owner=other_user)
        db.session.add(otherwarehouse)
        db.session.flush()
        otherwarehouse_id = otherwarehouse.id

    # Regular user should not see the private warehouse owned by other_user
    response = client.get(f"/inventory?warehouse={otherwarehouse_id}")
    assert response.status_code == 200
    assert otherwarehouse_name.encode() not in response.data


@pytest.mark.usefixtures("test_item")
def test_non_admin_stockout_access(client, regular_user, regular_warehouse):
    # Login as regular user
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    # Test access to stockout (stockout should be accessible to non-admin users)
    response = client.get("/stockout")
    assert response.status_code == 200
    assert b"warehouse" in response.data  # Check for warehouse field
    assert b"area" in response.data
    assert b"department" in response.data
    # Confirm we're on the stockout page
    assert "出库".encode() in response.data


@pytest.mark.usefixtures("test_item", "test_another_item")
def test_stockout_multiple_items(test_user, auth_client, test_warehouse, test_customer):
    # First add some inventory for multiple items
    with app.app_context():
        # Get first item
        item1 = ItemSKU.query.first()
        item2 = ItemSKU.query.filter(ItemSKU.id != item1.id).first()
        item1_display = _sku_display(item1)
        item2_display = _sku_display(item2)

    # Add inventory for first item
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "MULTI-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(item1.id),
            "items-0-quantity": "30",
            "items-0-price": "100.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Add inventory for second item
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "MULTI-TEST-002",
            "warehouse": test_warehouse,
            "items-0-item_id": str(item2.id),
            "items-0-quantity": "20",
            "items-0-price": "150.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Now attempt to stockout multiple items
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": item1_display,
            "items-0-item_sku_id": str(item1.id),
            "items-0-quantity": "5",
            "items-0-price": "110.00",
            "items-1-item_id": item2_display,
            "items-1-item_sku_id": str(item2.id),
            "items-1-quantity": "8",
            "items-1-price": "160.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

    # Verify the inventory was reduced for both items
    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        items = warehouse.item_skus
        assert len(items) == 2
        for item in items:
            if item.itemSKU_id == item1.id:
                assert item.count == 25  # 30 - 5 = 25
            elif item.itemSKU_id == item2.id:
                assert item.count == 12  # 20 - 8 = 12


def test_area_department_switching(auth_client, test_customer, test_warehouse):
    # Test selecting different areas and departments
    response = auth_client.post(
        "/stockout",
        data={
            "area": test_customer["area"],
            "warehouse": test_warehouse,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    response = auth_client.post(
        "/stockout",
        data={
            "department": test_customer["department"],
            "warehouse": test_warehouse,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("test_item")
def test_stockout_receipt_creation(auth_client, test_warehouse, test_customer):
    # Add inventory
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_display = _sku_display(sku)

    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "RECEIPT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "25",
            "items-0-price": "90.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        # Count receipts before stockout
        receipts_before = Receipt.query.filter_by(type=ReceiptType.STOCKOUT).count()

    # Perform stockout
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku.id),
            "items-0-quantity": "12",
            "items-0-price": "95.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data

    # Verify receipt was created properly
    with app.app_context():
        # Count should have increased
        receipts_after = Receipt.query.filter_by(type=ReceiptType.STOCKOUT).count()
        assert receipts_after == receipts_before + 1

        # Get the latest receipt
        receipt = (
            Receipt.query.filter_by(type=ReceiptType.STOCKOUT)
            .order_by(Receipt.id.desc())
            .first()
        )
        assert receipt is not None
        assert receipt.operator_id == 1  # admin user ID
        assert receipt.area_id == test_customer["area"]  # Verify area was saved
        assert (
            receipt.department_id == test_customer["department"]
        )  # Verify department was saved
        assert receipt.location == "测试地点"  # Verify location was saved

        # Check transaction details
        transaction = receipt.transactions[0]
        assert transaction.count == -12  # Negative for stockout
        assert transaction.price == 90.00
        assert transaction.itemSKU_id == sku.id


def test_missing_warehouse_selection(auth_client, test_customer):
    # Test submitting without a warehouse
    response = auth_client.post(
        "/stockout",
        data={
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": "1",
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Form validation should catch the missing warehouse
    assert b"This field is required" in response.data


@pytest.mark.usefixtures("test_item")
def test_warehouse_item_availability(
    auth_client, test_warehouse, public_warehouse, test_customer
):
    # Create a second warehouse and add items only to that warehouse
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_display = _sku_display(sku)

    # Add inventory to second warehouse only
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "WAREHOUSE-TEST-001",
            "warehouse": public_warehouse,
            "items-0-item_id": str(sku.id),
            "items-0-quantity": "15",
            "items-0-price": "70.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Now try to stockout from the first warehouse which shouldn't have the item
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert (
        "库存不足".encode() in response.data or "无效的物品".encode() in response.data
    )

    # Try with the second warehouse which has the stock
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": public_warehouse,
            "area": test_customer["area"],
            "department": test_customer["department"],
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku.id),
            "items-0-quantity": "5",
            "items-0-price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "出库成功".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_stockin_with_invalid_item_format(auth_client, test_warehouse):
    # Test with a non-numeric item ID that will trigger the ValueError exception
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "TEST-003",
            "warehouse": test_warehouse,
            "items-0-item_id": "not-a-number",  # Invalid format that will cause ValueError
            "items-0-quantity": "5",
            "items-0-price": "80.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "无效的物品".encode() in response.data


@pytest.mark.usefixtures("test_item")
def test_stockout_invalid_area_and_department(auth_client, test_warehouse):
    """Test stockout with invalid area and department IDs to cover error handling paths"""
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_id = sku.id
        sku_display = _sku_display(sku)
        # First add inventory so we can attempt stockout
        receipt = Receipt(
            operator_id=1,
            refcode="INVALID-AREA-TEST",
            warehouse_id=test_warehouse,
            type=ReceiptType.STOCKIN,
        )
        db.session.add(receipt)
        db.session.flush()
        transaction = Transaction(itemSKU=sku, count=20, price=50.00, receipt=receipt)
        db.session.add(transaction)
        db.session.commit()

    # Test with invalid area ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": 999,  # Non-existent area ID
            "department": 1,
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data

    # Test with invalid department ID
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": test_warehouse,
            "area": 1,
            "department": 999,  # Non-existent department ID
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data

    # Test with missing warehouse selection
    response = auth_client.post(
        "/stockout",
        data={
            "warehouse": 999,  # Non-existent warehouse ID
            "area": 1,
            "department": 1,
            "location": "测试地点",
            "items-0-item_id": sku_display,
            "items-0-item_sku_id": str(sku_id),
            "items-0-quantity": "5",
            "items-0-price": "60.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Not a valid choice." in response.data


@pytest.mark.usefixtures("test_item")
def test_inventory_export(auth_client, test_warehouse):
    """Test the inventory export functionality"""
    # Add some inventory to test with
    with app.app_context():
        sku = ItemSKU.query.first()
        sku_id = sku.id
        sku_item_name = sku.item.name
        sku_brand = sku.brand
        sku_spec = sku.spec

    # Add stock via stockin
    response = auth_client.post(
        "/stockin",
        data={
            "refcode": "EXPORT-TEST-001",
            "warehouse": test_warehouse,
            "items-0-item_id": str(sku_id),
            "items-0-quantity": "25",
            "items-0-price": "90.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    # Test basic export
    response = auth_client.get(f"/inventory/export?warehouse={test_warehouse}")
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "inventory_" in response.headers["Content-Disposition"]
    assert ".xlsx" in response.headers["Content-Disposition"]

    # Test export with search parameters
    response = auth_client.get(
        f"/inventory/export?warehouse={test_warehouse}&name={sku_item_name}&brand={sku_brand}&spec={sku_spec}"
    )
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Test export with non-matching search parameters
    response = auth_client.get(
        f"/inventory/export?warehouse={test_warehouse}&name=nonexistentitem"
    )
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Test without specifying warehouse (should default to first warehouse)
    response = auth_client.get("/inventory/export")
    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_inventory_export_invalid_warehouse(auth_client):
    """Test export with invalid warehouse selection"""
    # Test with non-existent warehouse ID
    response = auth_client.get(
        "/inventory/export?warehouse=99999", follow_redirects=True
    )
    assert response.status_code == 200
    assert "未选择有效的仓库".encode() in response.data

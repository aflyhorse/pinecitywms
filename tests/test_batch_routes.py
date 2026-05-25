import io
from wms.models import (
    Item,
    ItemSKU,
    Receipt,
    Transaction,
    ReceiptType,
    ToolInventory,
    WarehouseItemSKU,
    Warehouse,
    User,
)
from wms import app, db
import pandas as pd
from decimal import Decimal


def test_batch_stockin_get(client, auth_client, test_user):
    response = client.get("/batch_stockin")
    assert response.status_code == 200
    assert "批量入库" in response.get_data(as_text=True)


def test_batch_stockin_post_success(client, auth_client, test_user, test_warehouse):
    # Create test Excel file
    df = pd.DataFrame(
        {
            "物品": ["测试物品"],
            "品牌": ["测试品牌"],
            "规格": ["测试规格"],
            "数量": [10],
            "单价": [99.99],
        }
    )

    # Convert DataFrame to Excel bytes
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    # Prepare the file upload
    data = {"warehouse": test_warehouse, "file": (excel_file, "test.xlsx")}

    # Submit the form
    response = auth_client.post(
        "/batch_stockin",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "成功处理 1 条记录" in response.get_data(as_text=True)

    # Verify database changes
    item = db.session.execute(
        db.select(Item).filter_by(name="测试物品")
    ).scalar_one_or_none()
    assert item is not None

    sku = db.session.execute(
        db.select(ItemSKU).filter_by(item_id=item.id, brand="测试品牌", spec="测试规格")
    ).scalar_one_or_none()
    assert sku is not None

    receipt = db.session.execute(
        db.select(Receipt).filter_by(
            warehouse_id=test_warehouse, type=ReceiptType.STOCKIN
        )
    ).scalar_one_or_none()
    assert receipt is not None

    transaction = db.session.execute(
        db.select(Transaction).filter_by(itemSKU_id=sku.id, receipt_id=receipt.id)
    ).scalar_one_or_none()
    assert transaction is not None
    assert transaction.count == 10
    assert transaction.price == Decimal("99.99")


def test_batch_stockin_tool_inventory_targets_warehouse_owner(
    auth_client, regular_warehouse
):
    with app.app_context():
        owner_id = db.session.execute(
            db.select(User.id).filter_by(username="testuser")
        ).scalar_one()
        admin_id = db.session.execute(
            db.select(User.id).filter_by(username="testadmin")
        ).scalar_one()

        item = Item(name="批量入库工具物品", is_tool=True)
        db.session.add(item)
        db.session.flush()

        sku = ItemSKU(item_id=item.id, brand="工具品牌", spec="工具规格")
        db.session.add(sku)
        db.session.flush()
        sku_id = sku.id
        db.session.commit()

    df = pd.DataFrame(
        {
            "物品": ["批量入库工具物品"],
            "品牌": ["工具品牌"],
            "规格": ["工具规格"],
            "数量": [6],
            "单价": [12.50],
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    response = auth_client.post(
        "/batch_stockin",
        data={"warehouse": regular_warehouse, "file": (excel_file, "tool.xlsx")},
        follow_redirects=True,
        content_type="multipart/form-data",
    )
    assert "成功处理 1 条记录" in response.get_data(as_text=True)

    with app.app_context():
        owner_tool = ToolInventory.query.filter_by(
            user_id=owner_id, itemSKU_id=sku_id
        ).first()
        admin_tool = ToolInventory.query.filter_by(
            user_id=admin_id, itemSKU_id=sku_id
        ).first()
        assert owner_tool is not None
        assert owner_tool.count == 6
        assert admin_tool is None


def test_batch_stockin_tools_only_marks_new_and_existing_items(
    auth_client, test_warehouse
):
    with app.app_context():
        existing_item = Item(name="已有非工具物品", is_tool=False)
        db.session.add(existing_item)
        db.session.flush()
        existing_sku = ItemSKU(item_id=existing_item.id, brand="品牌A", spec="规格A")
        db.session.add(existing_sku)
        db.session.flush()

        # Existing stock should be seeded into ToolInventory after tools-only upload.
        existing_wis = WarehouseItemSKU(
            warehouse_id=test_warehouse,
            itemSKU_id=existing_sku.id,
            count=5,
            average_price=Decimal("7.20"),
        )
        db.session.add(existing_wis)
        db.session.commit()

    df = pd.DataFrame(
        {
            "物品": ["已有非工具物品", "全新物品"],
            "品牌": ["品牌A", "品牌B"],
            "规格": ["规格A", "规格B"],
            "数量": [1, 2],
            "单价": [3.5, 4.6],
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    response = auth_client.post(
        "/batch_stockin",
        data={
            "warehouse": test_warehouse,
            "tools_only": "y",
            "file": (excel_file, "tools_only.xlsx"),
        },
        follow_redirects=True,
        content_type="multipart/form-data",
    )
    assert "成功处理 2 条记录" in response.get_data(as_text=True)

    with app.app_context():
        warehouse = db.session.get(Warehouse, test_warehouse)
        owner_id = warehouse.owner_id
        existing_item = db.session.execute(
            db.select(Item).filter_by(name="已有非工具物品")
        ).scalar_one()
        new_item = db.session.execute(
            db.select(Item).filter_by(name="全新物品")
        ).scalar_one()
        assert existing_item.is_tool is True
        assert new_item.is_tool is True

        existing_sku = db.session.execute(
            db.select(ItemSKU).filter_by(
                item_id=existing_item.id, brand="品牌A", spec="规格A"
            )
        ).scalar_one()
        tool_row = ToolInventory.query.filter_by(
            user_id=owner_id, itemSKU_id=existing_sku.id
        ).first()
        assert tool_row is not None
        assert tool_row.count == 6  # 5 existing stock + 1 from this upload


def test_batch_stockin_invalid_file(client, auth_client, test_user, test_warehouse):
    # Test with invalid file extension
    data = {
        "warehouse": test_warehouse,
        "file": (io.BytesIO(b"invalid data"), "test.txt"),
    }

    response = auth_client.post(
        "/batch_stockin",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "请上传 Excel 文件" in response.get_data(as_text=True)


def test_batch_stockin_missing_columns(client, auth_client, test_user, test_warehouse):
    # Create Excel with missing columns
    df = pd.DataFrame(
        {
            "物品": ["测试物品"],
            "品牌": ["测试品牌"],
            # Missing '规格', '数量', '单价'
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    data = {"warehouse": test_warehouse, "file": (excel_file, "test.xlsx")}

    response = auth_client.post(
        "/batch_stockin",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "文件缺少必要的列" in response.get_data(as_text=True)


def test_stockin_template_download(client, auth_client, test_user):
    response = auth_client.get("/batch_stockin/template")

    assert response.status_code == 200
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Content-Type"] == content_type
    expected_disposition = "attachment; filename=stockin_template.xlsx"
    assert response.headers["Content-Disposition"] == expected_disposition

    # Verify the template content
    excel_data = pd.read_excel(io.BytesIO(response.data))
    required_columns = ["物品", "品牌", "规格", "数量", "单价"]
    assert all(col in excel_data.columns for col in required_columns)
    assert len(excel_data) == 1  # Should have one sample row
    assert excel_data.iloc[0]["物品"] == "样例-LED长方形灯"


def test_batch_stockin_unauthorized(client):
    # Test without login
    response = client.get("/batch_stockin")
    assert response.status_code == 302  # Should redirect to login

    response = client.get("/batch_stockin/template")
    assert response.status_code == 302  # Should redirect to login


def test_batch_takestock_get(client, auth_client, test_user):
    response = auth_client.get("/batch_takestock")
    assert response.status_code == 200
    assert "批量盘库" in response.get_data(as_text=True)


def test_batch_takestock_post_success(client, auth_client, test_user, test_warehouse):
    with app.app_context():
        # Create test item and SKU to test with
        item = Item(name="盘库测试物品")
        db.session.add(item)
        db.session.flush()

        sku = ItemSKU(item_id=item.id, brand="盘库测试品牌", spec="盘库测试规格")
        db.session.add(sku)
        db.session.flush()
        sku_id = sku.id

        # Add initial stock to warehouse
        wis = WarehouseItemSKU(warehouse_id=test_warehouse, itemSKU_id=sku.id, count=10)
        db.session.add(wis)
        db.session.commit()

    # Create test Excel file
    df = pd.DataFrame(
        {
            "物品": ["盘库测试物品"],
            "品牌": ["盘库测试品牌"],
            "规格": ["盘库测试规格"],
            "系统库存": [10],  # System inventory count
            "实际库存": [8],  # Actual inventory count (results in -2 adjustment)
        }
    )

    # Convert DataFrame to Excel bytes
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    # Prepare the file upload
    data = {
        "warehouse": test_warehouse,
        "note": "测试盘库",
        "file": (excel_file, "test.xlsx"),
    }

    # Submit the form
    response = auth_client.post(
        "/batch_takestock",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "成功处理 1 条记录" in response.get_data(as_text=True)

    with app.app_context():
        # Verify database changes
        receipt = db.session.execute(
            db.select(Receipt).filter_by(
                warehouse_id=test_warehouse, type=ReceiptType.TAKESTOCK, note="测试盘库"
            )
        ).scalar_one_or_none()
        assert receipt is not None

        transaction = db.session.execute(
            db.select(Transaction).filter_by(itemSKU_id=sku_id, receipt_id=receipt.id)
        ).scalar_one_or_none()
        assert transaction is not None
        assert transaction.count == -2

        # Verify the stock was updated
        updated_wis = db.session.execute(
            db.select(WarehouseItemSKU).filter_by(
                warehouse_id=test_warehouse, itemSKU_id=sku_id
            )
        ).scalar_one_or_none()
        assert updated_wis.count == 8  # 10 - 2


def test_batch_takestock_tool_inventory_targets_warehouse_owner(
    auth_client, regular_warehouse
):
    with app.app_context():
        owner_id = db.session.execute(
            db.select(User.id).filter_by(username="testuser")
        ).scalar_one()
        admin_id = db.session.execute(
            db.select(User.id).filter_by(username="testadmin")
        ).scalar_one()

        item = Item(name="批量盘库工具物品", is_tool=True)
        db.session.add(item)
        db.session.flush()

        sku = ItemSKU(item_id=item.id, brand="盘库工具品牌", spec="盘库工具规格")
        db.session.add(sku)
        db.session.flush()
        sku_id = sku.id

        db.session.add(
            WarehouseItemSKU(
                warehouse_id=regular_warehouse, itemSKU_id=sku_id, count=10
            )
        )
        db.session.add(
            ToolInventory(
                user_id=owner_id, itemSKU_id=sku_id, count=10, pending_scrap=0
            )
        )
        db.session.commit()

    df = pd.DataFrame(
        {
            "物品": ["批量盘库工具物品"],
            "品牌": ["盘库工具品牌"],
            "规格": ["盘库工具规格"],
            "系统库存": [10],
            "实际库存": [8],
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    response = auth_client.post(
        "/batch_takestock",
        data={
            "warehouse": regular_warehouse,
            "note": "工具盘库测试",
            "file": (excel_file, "takestock.xlsx"),
        },
        follow_redirects=True,
        content_type="multipart/form-data",
    )
    assert "成功处理 1 条记录" in response.get_data(as_text=True)

    with app.app_context():
        owner_tool = ToolInventory.query.filter_by(
            user_id=owner_id, itemSKU_id=sku_id
        ).first()
        admin_tool = ToolInventory.query.filter_by(
            user_id=admin_id, itemSKU_id=sku_id
        ).first()
        assert owner_tool is not None
        assert owner_tool.count == 8
        assert admin_tool is None


def test_batch_takestock_template_download(
    client, auth_client, test_user, test_warehouse
):
    # Create test item and stock for template download test
    item = Item(name="模板测试物品")
    db.session.add(item)
    db.session.flush()

    sku = ItemSKU(item_id=item.id, brand="模板测试品牌", spec="模板测试规格")
    db.session.add(sku)
    db.session.flush()

    # Add initial stock to warehouse
    wis = WarehouseItemSKU(warehouse_id=test_warehouse, itemSKU_id=sku.id, count=5)
    db.session.add(wis)
    db.session.commit()

    # Test downloading templates
    data = {
        "warehouse": test_warehouse,
        "download_template": "1",
        "only_with_stock": "y",  # Test with only in-stock items
    }

    response = auth_client.post("/batch_takestock", data=data)

    assert response.status_code == 200
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Content-Type"] == content_type

    # Verify the template content
    excel_data = pd.read_excel(io.BytesIO(response.data))
    required_columns = ["物品", "品牌", "规格", "系统库存", "实际库存"]
    assert all(col in excel_data.columns for col in required_columns)
    assert "模板测试物品" in excel_data["物品"].values

    # Test template without the only_with_stock filter
    data = {"warehouse": test_warehouse, "download_template": "1"}

    response = auth_client.post("/batch_takestock", data=data)
    assert response.status_code == 200


def test_batch_takestock_missing_columns(
    client, auth_client, test_user, test_warehouse
):
    # Create Excel with missing columns
    df = pd.DataFrame(
        {
            "物品": ["测试物品"],
            "品牌": ["测试品牌"],
            # Missing '规格', '系统库存', '实际库存'
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    data = {
        "warehouse": test_warehouse,
        "note": "测试盘库",
        "file": (excel_file, "test.xlsx"),
    }

    response = auth_client.post(
        "/batch_takestock",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "文件缺少必要的列" in response.get_data(as_text=True)


def test_batch_takestock_new_items(client, auth_client, test_user, test_warehouse):
    """Test that new items can be created during take stock"""
    # Create test Excel file with a new item that doesn't exist yet
    df = pd.DataFrame(
        {
            "物品": ["全新物品"],
            "品牌": ["全新品牌"],
            "规格": ["全新规格"],
            "系统库存": [0],  # System inventory count (doesn't exist yet)
            "实际库存": [5],  # Actual inventory (results in adding 5 new items)
        }
    )

    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    data = {
        "warehouse": test_warehouse,
        "note": "新增物品测试",
        "file": (excel_file, "test.xlsx"),
    }

    response = auth_client.post(
        "/batch_takestock",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    assert "成功处理 1 条记录" in response.get_data(as_text=True)

    # Verify the new item was created
    item = db.session.execute(
        db.select(Item).filter_by(name="全新物品")
    ).scalar_one_or_none()
    assert item is not None

    sku = db.session.execute(
        db.select(ItemSKU).filter_by(item_id=item.id, brand="全新品牌", spec="全新规格")
    ).scalar_one_or_none()
    assert sku is not None

    # Verify the stock was added to warehouse
    wis = db.session.execute(
        db.select(WarehouseItemSKU).filter_by(
            warehouse_id=test_warehouse, itemSKU_id=sku.id
        )
    ).scalar_one_or_none()
    assert wis is not None
    assert wis.count == 5

    # Wait 2 seconds to ensure the timestamp is different
    import time

    time.sleep(2)

    # Create another Excel file with the same item and stock
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    data["file"] = (excel_file, "test.xlsx")

    # Submit the same form again
    response = auth_client.post(
        "/batch_takestock",
        data=data,
        follow_redirects=True,
        content_type="multipart/form-data",
    )

    # Verify the response indicates no new records were processed
    assert "成功处理 0 条记录" in response.get_data(as_text=True)

    # Verify the stock wasn't added twice (should still be 5)
    wis = db.session.execute(
        db.select(WarehouseItemSKU).filter_by(
            warehouse_id=test_warehouse, itemSKU_id=sku.id
        )
    ).scalar_one_or_none()
    assert wis is not None
    assert wis.count == 5

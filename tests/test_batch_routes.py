import io
from wms.models import Item, ItemSKU, Receipt, Transaction, ReceiptType
from wms import db
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
            "价格": [99.99],
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
            # Missing '规格', '数量', '价格'
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
    required_columns = ["物品", "品牌", "规格", "数量", "价格"]
    assert all(col in excel_data.columns for col in required_columns)
    assert len(excel_data) == 1  # Should have one sample row
    assert excel_data.iloc[0]["物品"] == "样例物品"


def test_batch_stockin_unauthorized(client):
    # Test without login
    response = client.get("/batch_stockin")
    assert response.status_code == 302  # Should redirect to login

    response = client.get("/batch_stockin/template")
    assert response.status_code == 302  # Should redirect to login

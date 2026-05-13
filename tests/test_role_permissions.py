from wms import app, db
from wms.models import (
    User,
    Warehouse,
    Item,
    ItemSKU,
    ToolInventory,
    Employee,
    ToolReceipt,
    ToolTransaction,
    ToolReceiptType,
)


def test_auditor_can_view_all_warehouse_filters(auditor_client):
    with app.app_context():
        owner = User(username="owner1", nickname="Owner 1", is_admin=False)
        owner.set_password("password123")
        db.session.add(owner)
        db.session.flush()

        db.session.add(Warehouse(name="Owner Warehouse", owner_id=owner.id))
        db.session.add(Warehouse(name="Public Warehouse", is_public=True))
        db.session.commit()

    inv_resp = auditor_client.get("/inventory", follow_redirects=True)
    assert inv_resp.status_code == 200
    assert "Owner Warehouse".encode() in inv_resp.data
    assert "Public Warehouse".encode() in inv_resp.data

    rec_resp = auditor_client.get("/records", follow_redirects=True)
    assert rec_resp.status_code == 200
    assert "全部仓库".encode() in rec_resp.data

    usage_resp = auditor_client.get("/statistics_usage", follow_redirects=True)
    assert usage_resp.status_code == 200
    assert "全部仓库".encode() in usage_resp.data


def test_auditor_cannot_stockout(auditor_client):
    response = auditor_client.get("/stockout", follow_redirects=True)
    assert response.status_code == 200
    assert "审核员无权执行出库。".encode() in response.data


def test_auditor_can_view_fee_statistics(auditor_client):
    response = auditor_client.get("/statistics_fee", follow_redirects=True)
    assert response.status_code == 200


def test_regular_user_can_submit_scrap_request(client, regular_user):
    with app.app_context():
        regular_user_id = db.session.execute(
            db.select(User.id).filter_by(username="testuser")
        ).scalar_one()
        item = Item(name="普通用户报废申请工具")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="Brand", spec="Spec")
        db.session.add(sku)
        db.session.flush()
        sku_id = sku.id
        db.session.add(
            ToolInventory(
                user_id=regular_user_id,
                itemSKU_id=sku_id,
                count=2,
                pending_scrap=2,
            )
        )
        db.session.commit()

    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )
    get_response = client.get("/tools/scrap", follow_redirects=True)
    assert get_response.status_code == 200
    assert "工具报废".encode() in get_response.data
    assert "普通用户报废申请工具".encode() in get_response.data

    post_response = client.post(
        "/tools/scrap",
        data={"sku_ids[]": [str(sku_id)]},
        follow_redirects=True,
    )
    assert post_response.status_code == 200
    assert "报废申请已提交，等待审核员确认。".encode() in post_response.data


def test_auditor_can_access_scrap_page(auditor_client):
    response = auditor_client.get("/tools/scrap", follow_redirects=True)
    assert response.status_code == 200
    assert "待审核报废申请单".encode() in response.data


def test_auditor_tool_pages_support_user_scope(auditor_client):
    with app.app_context():
        user_a = User(username="groupa", nickname="班组A", is_admin=False)
        user_a.set_password("password123")
        user_b = User(username="groupb", nickname="班组B", is_admin=False)
        user_b.set_password("password123")
        db.session.add_all([user_a, user_b])
        db.session.flush()

        item1 = Item(name="范围测试工具A")
        item2 = Item(name="范围测试工具B")
        db.session.add_all([item1, item2])
        db.session.flush()
        sku_a = ItemSKU(item_id=item1.id, brand="BrandA", spec="SpecA")
        sku_b = ItemSKU(item_id=item2.id, brand="BrandB", spec="SpecB")
        db.session.add_all([sku_a, sku_b])
        db.session.flush()

        db.session.add(
            ToolInventory(
                user_id=user_a.id, itemSKU_id=sku_a.id, count=5, pending_scrap=2
            )
        )
        db.session.add(
            ToolInventory(
                user_id=user_b.id, itemSKU_id=sku_b.id, count=7, pending_scrap=3
            )
        )

        db.session.add(Employee(employee_id="A001", name="员工A", user_id=user_a.id))
        db.session.add(Employee(employee_id="B001", name="员工B", user_id=user_b.id))

        db.session.add(
            ToolReceipt(
                type=ToolReceiptType.RETURN, operator_id=user_a.id, printed=True
            )
        )
        db.session.add(
            ToolReceipt(
                type=ToolReceiptType.RETURN, operator_id=user_b.id, printed=True
            )
        )

        req_a = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            operator_id=user_a.id,
            target_user_id=user_a.id,
            printed=False,
        )
        req_b = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            operator_id=user_b.id,
            target_user_id=user_b.id,
            printed=False,
        )
        db.session.add_all([req_a, req_b])
        db.session.flush()
        db.session.add(
            ToolTransaction(
                tool_receipt_id=req_a.id,
                itemSKU_id=sku_a.id,
                count=1,
                employee_id=None,
            )
        )
        db.session.add(
            ToolTransaction(
                tool_receipt_id=req_b.id,
                itemSKU_id=sku_b.id,
                count=1,
                employee_id=None,
            )
        )
        db.session.commit()

        user_a_id = user_a.id

    req_resp = auditor_client.get(
        f"/tools/requisition?user_id={user_a_id}", follow_redirects=True
    )
    assert req_resp.status_code == 200
    assert "员工A".encode() in req_resp.data
    assert "员工B".encode() not in req_resp.data
    assert "范围测试工具A".encode() in req_resp.data
    assert "范围测试工具B".encode() not in req_resp.data

    scrap_resp = auditor_client.get("/tools/scrap", follow_redirects=True)
    assert scrap_resp.status_code == 200
    assert "班组A".encode() in scrap_resp.data
    assert "班组B".encode() in scrap_resp.data

    print_resp = auditor_client.get(
        f"/tools/print?user_id={user_a_id}", follow_redirects=True
    )
    assert print_resp.status_code == 200
    assert "班组A".encode() in print_resp.data
    assert print_resp.data.count("/tools/print/".encode()) == 2


def test_tool_print_defaults_to_auditor_own_receipts(auditor_client):
    with app.app_context():
        other = User(username="printowner", nickname="打印班组", is_admin=False)
        other.set_password("password123")
        db.session.add(other)
        db.session.flush()

        auditor = User.query.filter_by(username="testauditor").first()
        db.session.add(
            ToolReceipt(
                type=ToolReceiptType.SCRAP, operator_id=auditor.id, printed=True
            )
        )
        db.session.add(
            ToolReceipt(type=ToolReceiptType.SCRAP, operator_id=other.id, printed=True)
        )
        db.session.commit()

    response = auditor_client.get("/tools/print", follow_redirects=True)
    assert response.status_code == 200
    assert "Test Auditor".encode() in response.data
    assert response.data.count("/tools/print/".encode()) == 1


def test_regular_user_can_view_auditor_scrap_targeted_to_self(client, regular_user):
    with app.app_context():
        regular_user_id = db.session.execute(
            db.select(User.id).filter_by(username="testuser")
        ).scalar_one()
        auditor = User(
            username="auditorx",
            nickname="审核员X",
            is_admin=False,
            is_auditor=True,
        )
        auditor.set_password("password123")
        db.session.add(auditor)
        db.session.flush()
        receipt = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            operator_id=auditor.id,
            target_user_id=regular_user_id,
            printed=True,
        )
        db.session.add(receipt)
        db.session.commit()
        receipt_id = receipt.id

    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
    )

    list_resp = client.get("/tools/print", follow_redirects=True)
    assert list_resp.status_code == 200
    assert "testuser".encode() not in list_resp.data
    assert "Test User".encode() in list_resp.data
    assert list_resp.data.count("/tools/print/".encode()) == 1

    detail_resp = client.get(f"/tools/print/{receipt_id}", follow_redirects=True)
    assert detail_resp.status_code == 200
    assert "Test User".encode() in detail_resp.data

import uuid

from wms import app, db
from wms.models import (
    Department,
    Area,
    Employee,
    EmployeeToolHolding,
    Item,
    ItemSKU,
    Receipt,
    ReceiptType,
    ToolInventory,
    ToolReceipt,
    ToolReceiptType,
    ToolTransaction,
    Transaction,
    User,
    Warehouse,
    WarehouseItemSKU,
)


def _login(client, username: str, password: str = "password123"):
    return client.post(
        "/login",
        data={"username": username, "password": password, "remember": "y"},
        follow_redirects=True,
    )


def _create_tool_sku(name_prefix: str = "工具"):
    item = Item(name=f"{name_prefix}-{uuid.uuid4()}")
    db.session.add(item)
    db.session.flush()
    sku = ItemSKU(item_id=item.id, brand="Brand", spec="Spec")
    db.session.add(sku)
    db.session.flush()
    return sku


def _user_id(username: str) -> int:
    return db.session.execute(
        db.select(User.id).filter_by(username=username)
    ).scalar_one()


def test_employees_get_and_include_resigned(client, regular_user):
    with app.app_context():
        regular_user_id = _user_id("testuser")
        active = Employee(employee_id="E100", name="在职员工", user_id=regular_user_id)
        resigned = Employee(
            employee_id="E101",
            name="离职员工",
            user_id=regular_user_id,
            is_resigned=True,
        )
        db.session.add_all([active, resigned])
        db.session.commit()

    _login(client, "testuser")

    resp_default = client.get("/employees", follow_redirects=True)
    assert resp_default.status_code == 200
    assert "在职员工".encode() in resp_default.data

    resp_all = client.get("/employees?include_resigned=1", follow_redirects=True)
    assert resp_all.status_code == 200
    assert "离职员工".encode() in resp_all.data


def test_employees_post_create_duplicate_and_regular_scope(client, regular_user):
    with app.app_context():
        regular_user_id = _user_id("testuser")

    _login(client, "testuser")
    create_resp = client.post(
        "/employees",
        data={
            "employee_id": "E200",
            "name": "普通用户员工",
            "user_id": str(regular_user_id),
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200
    assert "添加成功".encode() in create_resp.data

    with app.app_context():
        created = Employee.query.filter_by(employee_id="E200").first()
        assert created is not None
        assert created.user_id == regular_user_id

    dup_resp = client.post(
        "/employees",
        data={"employee_id": "E200", "name": "重复", "user_id": str(regular_user_id)},
        follow_redirects=True,
    )
    assert dup_resp.status_code == 200
    assert "已存在".encode() in dup_resp.data


def test_employees_auditor_cannot_create_and_can_list(auditor_client):
    resp = auditor_client.post(
        "/employees",
        data={"employee_id": "E300", "name": "审核员尝试新增", "user_id": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "审核员无权新增员工".encode() in resp.data


def test_employee_resign_flow_and_holding_check(auth_client, regular_user):
    with app.app_context():
        regular_user_id = _user_id("testuser")
        emp_ok = Employee(employee_id="E400", name="可离职", user_id=regular_user_id)
        emp_blocked = Employee(
            employee_id="E401", name="持有工具", user_id=regular_user_id
        )
        db.session.add_all([emp_ok, emp_blocked])
        db.session.flush()

        sku = _create_tool_sku("离职校验")
        db.session.add(
            EmployeeToolHolding(employee_id=emp_blocked.id, itemSKU_id=sku.id, count=2)
        )
        db.session.commit()

        emp_ok_id = emp_ok.id
        emp_blocked_id = emp_blocked.id

    blocked_resp = auth_client.post(
        f"/employee/{emp_blocked_id}/resign", follow_redirects=True
    )
    assert blocked_resp.status_code == 200
    assert "请先归还工具".encode() in blocked_resp.data

    ok_resp = auth_client.post(f"/employee/{emp_ok_id}/resign", follow_redirects=True)
    assert ok_resp.status_code == 200
    assert "已标记为离职".encode() in ok_resp.data

    with app.app_context():
        emp = db.session.get(Employee, emp_ok_id)
        assert emp.is_resigned is True


def test_employee_resign_permissions(auditor_client, client):
    with app.app_context():
        user_a = User(username="u_a", nickname="用户A", is_admin=False)
        user_a.set_password("password123")
        user_b = User(username="u_b", nickname="用户B", is_admin=False)
        user_b.set_password("password123")
        db.session.add_all([user_a, user_b])
        db.session.flush()
        emp = Employee(employee_id="E500", name="跨班组员工", user_id=user_b.id)
        db.session.add(emp)
        db.session.commit()
        emp_id = emp.id

    auditor_resp = auditor_client.post(
        f"/employee/{emp_id}/resign", follow_redirects=True
    )
    assert auditor_resp.status_code == 200
    assert "审核员无权办理离职".encode() in auditor_resp.data

    _login(client, "u_a")
    denied_resp = client.post(f"/employee/{emp_id}/resign", follow_redirects=True)
    assert denied_resp.status_code == 200
    assert "无权操作该员工".encode() in denied_resp.data

    missing_resp = client.post("/employee/9999/resign", follow_redirects=True)
    assert missing_resp.status_code == 200


def test_tool_requisition_validation_and_success(auth_client, regular_user):
    with app.app_context():
        admin = User.query.filter_by(username="testadmin").first()
        regular_user_id = _user_id("testuser")
        regular = db.session.get(User, regular_user_id)
        emp = Employee(employee_id="E600", name="领用员工", user_id=regular.id)
        db.session.add(emp)
        db.session.flush()
        emp_id = emp.id

        sku_ok = _create_tool_sku("领用成功")
        sku_low = _create_tool_sku("领用不足")
        db.session.add(
            ToolInventory(
                user_id=regular.id, itemSKU_id=sku_ok.id, count=5, pending_scrap=0
            )
        )
        db.session.add(
            ToolInventory(
                user_id=regular.id, itemSKU_id=sku_low.id, count=1, pending_scrap=0
            )
        )
        db.session.commit()

        admin_id = admin.id
        regular_id = regular.id
        sku_ok_id = sku_ok.id
        sku_low_id = sku_low.id

    missing_emp = auth_client.post(
        "/tools/requisition",
        data={"scope_user_id": str(regular_id), "sku_ids[]": [str(sku_ok_id)]},
        follow_redirects=True,
    )
    assert "请选择员工".encode() in missing_emp.data

    missing_sku = auth_client.post(
        "/tools/requisition",
        data={"scope_user_id": str(regular_id), "employee_id": str(emp_id)},
        follow_redirects=True,
    )
    assert "请至少选择一种工具".encode() in missing_sku.data

    mismatch_scope = auth_client.post(
        "/tools/requisition",
        data={
            "scope_user_id": str(admin_id),
            "employee_id": str(emp_id),
            "sku_ids[]": [str(sku_ok_id)],
        },
        follow_redirects=True,
    )
    assert "不属于当前查看用户".encode() in mismatch_scope.data

    invalid_qty = auth_client.post(
        "/tools/requisition",
        data={
            "scope_user_id": str(regular_id),
            "employee_id": str(emp_id),
            "sku_ids[]": [str(sku_ok_id)],
            f"qty_{sku_ok_id}": "0",
        },
        follow_redirects=True,
    )
    assert "领用数量必须大于 0".encode() in invalid_qty.data

    insufficient = auth_client.post(
        "/tools/requisition",
        data={
            "scope_user_id": str(regular_id),
            "employee_id": str(emp_id),
            "sku_ids[]": [str(sku_low_id)],
            f"qty_{sku_low_id}": "2",
        },
        follow_redirects=True,
    )
    assert "库内余量不足".encode() in insufficient.data

    success = auth_client.post(
        "/tools/requisition",
        data={
            "scope_user_id": str(regular_id),
            "employee_id": str(emp_id),
            "sku_ids[]": [str(sku_ok_id)],
            f"qty_{sku_ok_id}": "3",
        },
        follow_redirects=True,
    )
    assert success.status_code == 200
    assert "办理工具领用".encode() in success.data

    with app.app_context():
        ti = ToolInventory.query.filter_by(
            user_id=regular_id, itemSKU_id=sku_ok_id
        ).first()
        holding = EmployeeToolHolding.query.filter_by(
            employee_id=emp_id, itemSKU_id=sku_ok_id
        ).first()
        assert ti.count == 2
        assert holding.count == 3
        assert (
            ToolReceipt.query.filter_by(
                type=ToolReceiptType.REQUISITION, employee_id=emp_id
            ).count()
            == 1
        )


def test_tool_requisition_auditor_cannot_post(auditor_client):
    resp = auditor_client.post(
        "/tools/requisition",
        data={"employee_id": "1", "sku_ids[]": ["1"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "审核员仅可按用户查看工具领用数据，不可提交".encode() in resp.data


def test_tool_employee_detail_branches(auth_client, regular_user):
    with app.app_context():
        regular_user_id = _user_id("testuser")
        regular = db.session.get(User, regular_user_id)
        emp = Employee(employee_id="E700", name="更换归还员工", user_id=regular.id)
        db.session.add(emp)
        db.session.flush()

        sku = _create_tool_sku("更换归还")
        db.session.add(
            ToolInventory(
                user_id=regular.id, itemSKU_id=sku.id, count=3, pending_scrap=0
            )
        )
        db.session.add(
            EmployeeToolHolding(employee_id=emp.id, itemSKU_id=sku.id, count=2)
        )
        db.session.commit()

        emp_id = emp.id
        sku_id = sku.id
        regular_id = regular.id

    invalid_action = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "bad", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "1"},
        follow_redirects=True,
    )
    assert "无效的操作类型".encode() in invalid_action.data

    missing_sku = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "return"},
        follow_redirects=True,
    )
    assert "请至少选择一种工具".encode() in missing_sku.data

    too_many = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "return", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "5"},
        follow_redirects=True,
    )
    assert "员工持有数量不足".encode() in too_many.data

    exchange_short = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "exchange", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "4"},
        follow_redirects=True,
    )
    assert "员工持有数量不足".encode() in exchange_short.data

    success_return = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "return", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "1"},
        follow_redirects=True,
    )
    assert success_return.status_code == 200
    assert "办理工具归还".encode() in success_return.data

    success_exchange = auth_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "exchange", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "1"},
        follow_redirects=True,
    )
    assert success_exchange.status_code == 200
    assert "办理工具更换".encode() in success_exchange.data

    with app.app_context():
        ti = ToolInventory.query.filter_by(
            user_id=regular_id, itemSKU_id=sku_id
        ).first()
        holding = EmployeeToolHolding.query.filter_by(
            employee_id=emp_id, itemSKU_id=sku_id
        ).first()
        assert ti.count == 3
        assert ti.pending_scrap == 1
        assert holding.count == 1
        assert ToolReceipt.query.filter_by(type=ToolReceiptType.RETURN).count() >= 1
        assert ToolReceipt.query.filter_by(type=ToolReceiptType.EXCHANGE).count() >= 1

    missing_emp = auth_client.get("/tools/employee/9999", follow_redirects=True)
    assert missing_emp.status_code == 200


def test_tool_employee_detail_auditor_blocked(auditor_client, regular_user):
    with app.app_context():
        regular_user_id = _user_id("testuser")
        emp = Employee(employee_id="E701", name="审核员阻断员工", user_id=regular_user_id)
        db.session.add(emp)
        db.session.flush()

        sku = _create_tool_sku("审核员阻断")
        db.session.add(EmployeeToolHolding(employee_id=emp.id, itemSKU_id=sku.id, count=1))
        db.session.commit()

        emp_id = emp.id
        sku_id = sku.id

    auditor_blocked = auditor_client.post(
        f"/tools/employee/{emp_id}",
        data={"action": "return", "sku_ids[]": [str(sku_id)], f"qty_{sku_id}": "1"},
        follow_redirects=True,
    )
    assert "审核员仅可查看，不可执行更换/归还".encode() in auditor_blocked.data


def test_tool_scrap_user_validations_and_auditor_confirm(
    client, regular_user, auditor_user
):
    _login(client, "testuser")

    with app.app_context():
        regular_user_id = db.session.execute(
            db.select(User.id).filter_by(username="testuser")
        ).scalar_one()

        sku = _create_tool_sku("报废审核")
        db.session.add(
            ToolInventory(
                user_id=regular_user_id, itemSKU_id=sku.id, count=8, pending_scrap=2
            )
        )

        warehouse = Warehouse(name="班组仓库", owner_id=regular_user_id)
        db.session.add(warehouse)
        db.session.flush()
        db.session.add(
            WarehouseItemSKU(
                warehouse_id=warehouse.id,
                itemSKU_id=sku.id,
                count=10,
                average_price=3,
            )
        )
        db.session.commit()

        sku_id = sku.id

    no_selection = client.post("/tools/scrap", data={}, follow_redirects=True)
    assert "请至少选择一种工具".encode() in no_selection.data

    with app.app_context():
        ti = ToolInventory.query.filter_by(
            user_id=regular_user_id, itemSKU_id=sku_id
        ).first()
        ti.pending_scrap = 0
        db.session.commit()

    no_pending = client.post(
        "/tools/scrap",
        data={"sku_ids[]": [str(sku_id)]},
        follow_redirects=True,
    )
    assert "均无待报废数量".encode() in no_pending.data

    with app.app_context():
        ti = ToolInventory.query.filter_by(
            user_id=regular_user_id, itemSKU_id=sku_id
        ).first()
        ti.pending_scrap = 2
        req = ToolReceipt(
            type=ToolReceiptType.SCRAP,
            target_user_id=regular_user_id,
            operator_id=regular_user_id,
            printed=False,
        )
        db.session.add(req)
        db.session.flush()
        db.session.add(
            ToolTransaction(
                tool_receipt_id=req.id, itemSKU_id=sku_id, count=2, employee_id=None
            )
        )
        db.session.commit()
        req_id = req.id

    _login(client, "testauditor")
    empty_confirm = client.post("/tools/scrap", data={}, follow_redirects=True)
    assert "请至少选择一张报废申请单".encode() in empty_confirm.data

    confirm_resp = client.post(
        "/tools/scrap",
        data={"request_ids[]": [str(req_id)]},
        follow_redirects=True,
    )
    assert confirm_resp.status_code == 200
    assert "已确认 1 张报废申请单".encode() in confirm_resp.data

    with app.app_context():
        auditor = db.session.execute(
            db.select(User).filter_by(username="testauditor")
        ).scalar_one()
        req = db.session.get(ToolReceipt, req_id)
        ti = ToolInventory.query.filter_by(
            user_id=regular_user_id, itemSKU_id=sku_id
        ).first()
        assert req.receipt_id is not None
        assert req.printed is True
        assert req.confirmed_by_id == auditor.id
        assert ti.pending_scrap == 0

        wh_receipt = db.session.get(Receipt, req.receipt_id)
        assert wh_receipt.type == ReceiptType.STOCKOUT
        assert wh_receipt.area_id is not None
        assert wh_receipt.department_id is not None
        tx = Transaction.query.filter_by(
            receipt_id=wh_receipt.id, itemSKU_id=sku_id
        ).first()
        assert tx.count == -2

        assert Area.query.filter_by(name="班组").first() is not None
        assert Department.query.filter_by(name="设备管理科").first() is not None


def test_tool_print_detail_and_toggle_permissions(client):
    with app.app_context():
        owner = User(username="print_owner", nickname="打印拥有者", is_admin=False)
        owner.set_password("password123")
        other = User(username="print_other", nickname="打印其他人", is_admin=False)
        other.set_password("password123")
        auditor = User(
            username="print_auditor",
            nickname="打印审核员",
            is_admin=False,
            is_auditor=True,
        )
        auditor.set_password("password123")
        db.session.add_all([owner, other, auditor])
        db.session.flush()

        receipt = ToolReceipt(
            type=ToolReceiptType.RETURN, operator_id=owner.id, printed=False
        )
        db.session.add(receipt)
        db.session.commit()
        receipt_id = receipt.id

    _login(client, "print_other")
    missing = client.get("/tools/print/9999", follow_redirects=True)
    assert "单据不存在".encode() in missing.data

    forbidden = client.get(f"/tools/print/{receipt_id}", follow_redirects=True)
    assert "无权查看该单据".encode() in forbidden.data

    toggle_forbidden = client.post(
        f"/tools/print/{receipt_id}/toggle-printed", follow_redirects=True
    )
    assert "无权操作该单据".encode() in toggle_forbidden.data

    _login(client, "print_auditor")
    toggle_auditor = client.post(
        f"/tools/print/{receipt_id}/toggle-printed", follow_redirects=True
    )
    assert "审核员无权修改打印状态".encode() in toggle_auditor.data

    _login(client, "print_owner")
    toggle_on = client.post(
        f"/tools/print/{receipt_id}/toggle-printed", follow_redirects=True
    )
    assert "已标记为已打印".encode() in toggle_on.data

    toggle_off = client.post(
        f"/tools/print/{receipt_id}/toggle-printed", follow_redirects=True
    )
    assert "已取消“已打印”状态".encode() in toggle_off.data


def test_tool_print_post_mark_printed(auth_client):
    with app.app_context():
        admin = User.query.filter_by(username="testadmin").first()
        r1 = ToolReceipt(
            type=ToolReceiptType.RETURN, operator_id=admin.id, printed=False
        )
        r2 = ToolReceipt(
            type=ToolReceiptType.EXCHANGE, operator_id=admin.id, printed=False
        )
        db.session.add_all([r1, r2])
        db.session.commit()
        r1_id = r1.id
        r2_id = r2.id

    resp = auth_client.post(
        "/tools/print",
        data={"receipt_ids[]": [str(r1_id), str(r2_id)]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "标记为已打印".encode() in resp.data

    with app.app_context():
        assert db.session.get(ToolReceipt, r1_id).printed is True
        assert db.session.get(ToolReceipt, r2_id).printed is True

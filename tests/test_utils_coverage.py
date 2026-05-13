"""Comprehensive tests for wms.utils to improve coverage."""

from wms import db
from wms.models import User, ToolReceipt, ToolReceiptType
from wms.utils import user_can_view_tool_receipt


def test_user_can_view_tool_receipt_none_receipt():
    """Test permission check with None receipt."""
    admin = User(username="testadmin", nickname="Test Admin", is_admin=True)
    admin.id = 1
    result = user_can_view_tool_receipt(admin, None)
    assert result is False


def test_user_can_view_tool_receipt_auditor_can_view_any():
    """Test that auditors can view any receipt."""
    auditor = User(username="testauditor", nickname="Test Auditor", is_auditor=True)
    auditor.id = 1
    regular = User(username="testuser", nickname="Test User", is_admin=False)
    regular.id = 2

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=regular.id, printed=False
    )

    result = user_can_view_tool_receipt(auditor, receipt)
    assert result is True


def test_user_can_view_tool_receipt_admin_can_view_any():
    """Test that admins can view any receipt."""
    admin = User(username="testadmin", nickname="Test Admin", is_admin=True)
    admin.id = 1
    regular = User(username="testuser", nickname="Test User", is_admin=False)
    regular.id = 2

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=regular.id, printed=False
    )

    result = user_can_view_tool_receipt(admin, receipt)
    assert result is True


def test_user_can_view_tool_receipt_operator_can_view_own():
    """Test that an operator can view their own receipt."""
    user = User(username="testuser", nickname="Test User", is_admin=False)
    user.id = 1

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=user.id, printed=False
    )

    result = user_can_view_tool_receipt(user, receipt)
    assert result is True


def test_user_can_view_tool_receipt_target_user_can_view_scrap():
    """Test that target_user can view scrap receipts targeted at them."""
    user_a = User(username="view_target_a", nickname="查看目标A", is_admin=False)
    user_a.id = 1
    user_b = User(username="view_target_b", nickname="查看目标B", is_admin=False)
    user_b.id = 2

    receipt = ToolReceipt(
        type=ToolReceiptType.SCRAP,
        operator_id=user_a.id,
        target_user_id=user_b.id,
        printed=False,
    )

    # user_b (target_user) can view
    result = user_can_view_tool_receipt(user_b, receipt)
    assert result is True


def test_user_can_view_tool_receipt_non_target_cannot_view():
    """Test that a user who is neither operator nor target cannot view."""
    user_a = User(username="view_a", nickname="查看A", is_admin=False)
    user_a.id = 1
    user_b = User(username="view_b", nickname="查看B", is_admin=False)
    user_b.id = 2
    user_c = User(username="view_c", nickname="查看C", is_admin=False)
    user_c.id = 3

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=user_a.id, printed=False
    )

    # user_c cannot view (not operator, not auditor/admin)
    result = user_can_view_tool_receipt(user_c, receipt)
    assert result is False


def test_user_can_view_tool_receipt_with_none_attributes():
    """Test permission check when receipt has None operator_id or target_user_id."""
    admin = User(username="testadmin", nickname="Test Admin", is_admin=True)
    admin.id = 1

    receipt = ToolReceipt(
        type=ToolReceiptType.SCRAP,
        operator_id=admin.id,
        target_user_id=None,
        printed=False,
    )

    # Admin can view
    result = user_can_view_tool_receipt(admin, receipt)
    assert result is True


def test_tool_receipt_view_required_decorator_nonexistent_receipt(auth_client):
    """Test decorator when receipt ID doesn't exist."""
    resp = auth_client.get("/tools/print/9999", follow_redirects=True)
    assert resp.status_code == 200


def test_tool_receipt_view_required_decorator_unauthorized(client):
    """Test decorator when user is not authorized to view."""
    owner = User(username="dec_owner", nickname="装饰器拥有者", is_admin=False)
    owner.set_password("password123")
    other = User(username="dec_other", nickname="装饰器其他人", is_admin=False)
    other.set_password("password123")
    db.session.add_all([owner, other])
    db.session.flush()

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=owner.id, printed=False
    )
    db.session.add(receipt)
    db.session.commit()
    receipt_id = receipt.id

    client.post(
        "/login",
        data={"username": "dec_other", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )

    resp = client.get(f"/tools/print/{receipt_id}", follow_redirects=True)
    assert resp.status_code == 200
    assert "无权查看该单据".encode() in resp.data


def test_admin_or_auditor_required_regular_user_denied(client):
    """Test admin_or_auditor_required decorator denies regular users."""
    client.post(
        "/login",
        data={"username": "testuser", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )

    # Try to access statistics_fee which requires admin or auditor
    resp = client.get("/statistics_fee", follow_redirects=True)
    assert resp.status_code == 200


def test_admin_or_auditor_required_auditor_allowed(auditor_client):
    """Test admin_or_auditor_required decorator allows auditors."""
    resp = auditor_client.get("/statistics_fee", follow_redirects=True)
    assert resp.status_code == 200


def test_admin_or_auditor_required_admin_allowed(auth_client):
    """Test admin_or_auditor_required decorator allows admins."""
    resp = auth_client.get("/statistics_fee", follow_redirects=True)
    assert resp.status_code == 200


def test_tool_receipt_view_required_with_receipt_id_in_args(auth_client):
    """Test decorator gets receipt_id from query args."""
    admin = User.query.filter_by(username="testadmin").first()

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=admin.id, printed=False
    )
    db.session.add(receipt)
    db.session.commit()
    receipt_id = receipt.id

    resp = auth_client.get(f"/tools/print/{receipt_id}")
    assert resp.status_code == 200


def test_user_can_view_tool_receipt_with_object_missing_attributes():
    """Test user_can_view_tool_receipt handles objects with missing attributes gracefully."""
    admin = User(username="testadmin", nickname="Test Admin", is_admin=True)
    admin.id = 1

    class FakeReceipt:
        pass

    fake_receipt = FakeReceipt()

    result = user_can_view_tool_receipt(admin, fake_receipt)
    assert result is True


def test_user_can_view_tool_receipt_user_without_can_view_property():
    """Test permission check with user object without can_view_all_tool_groups."""
    regular = User(username="testuser", nickname="Test User", is_admin=False)
    regular.id = 1

    receipt = ToolReceipt(
        type=ToolReceiptType.RETURN, operator_id=regular.id, printed=False
    )

    result = user_can_view_tool_receipt(regular, receipt)
    assert result is True


def test_admin_required_allows_admin(auth_client):
    """Test admin_required decorator allows admin users."""
    resp = auth_client.get("/item")
    assert resp.status_code == 200

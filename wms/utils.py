from flask import flash, redirect, url_for
from flask_login import current_user
from functools import wraps
from flask import request
from wms import db


def user_can_view_tool_receipt(user, tool_receipt) -> bool:
    """Return True if `user` may view the given ToolReceipt object.

    This centralizes the permission logic: admins/auditors or the operator
    or the target_user may view the receipt.
    """
    if not tool_receipt:
        return False
    if getattr(user, "can_view_all_tool_groups", False):
        return True
    if getattr(tool_receipt, "operator_id", None) == getattr(user, "id", None):
        return True
    if getattr(tool_receipt, "target_user_id", None) and (
        getattr(tool_receipt, "target_user_id") == getattr(user, "id", None)
    ):
        return True
    return False


def tool_receipt_view_required(f):
    """Decorator to require that the current user may view a ToolReceipt.

    The decorator expects the route to provide `receipt_id` as a path
    parameter (kwargs) or as `receipt_id` in the query string.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        receipt_id = kwargs.get("receipt_id") or request.args.get(
            "receipt_id", type=int
        )
        if not receipt_id:
            flash("未指定单据ID。", "danger")
            return redirect(url_for("tool_print"))

        # Import here to avoid circular import at module load
        from wms.models import ToolReceipt

        tool_receipt = db.session.get(ToolReceipt, receipt_id)
        if not tool_receipt:
            flash("单据不存在。", "danger")
            return redirect(url_for("tool_print"))

        if not user_can_view_tool_receipt(current_user, tool_receipt):
            flash("无权查看该单据。", "danger")
            return redirect(url_for("tool_print"))

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("Unauthorized Access.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def admin_or_auditor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not (current_user.is_admin or current_user.is_auditor):
            flash("Unauthorized Access.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def deny_auditor_write_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_auditor:
            flash("审核员仅支持查看与报废确认单生成。", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def _escape_like(val: str) -> str:
    if val is None:
        return val
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

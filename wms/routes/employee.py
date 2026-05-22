from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from wms import app, db
from wms.models import Employee, User, EmployeeToolHolding
from wms.forms import EmployeeCreateForm


def _employee_queryset():
    """Return base Employee query filtered to current user's scope."""
    q = Employee.query
    # Allow auditors (and admins) to view all employees, but non-admin/non-auditor users only see their own
    if not current_user.can_view_all_tool_groups:
        q = q.filter(Employee.user_id == current_user.id)
    return q


def _check_employee_access(emp: Employee) -> bool:
    """Return True if current user may manage this employee."""
    if current_user.is_admin:
        return True
    if emp.user_id != current_user.id:
        flash("无权操作该员工。", "danger")
        return False
    return True


@app.route("/employees", methods=["GET", "POST"])
@login_required
def employees():
    """Employee management: list all employees and add new ones."""
    include_resigned = request.args.get("include_resigned") == "1"
    form = EmployeeCreateForm()

    # Populate user choices — admins pick any user, non-admins fixed to self
    if current_user.is_admin:
        users = User.query.order_by(User.nickname).all()
        form.user_id.choices = [(u.id, u.nickname) for u in users]
    else:
        form.user_id.choices = [(current_user.id, current_user.nickname)]

    if request.method == "POST" and not current_user.can_manage_employees:
        flash("审核员无权新增员工。", "danger")
        return redirect(
            url_for("employees", include_resigned="1" if include_resigned else "0")
        )

    if form.validate_on_submit():
        user_id = form.user_id.data if current_user.is_admin else current_user.id
        existing = Employee.query.filter_by(employee_id=form.employee_id.data).first()
        if existing:
            flash(f"工号 {form.employee_id.data} 已存在。", "danger")
        else:
            emp = Employee(
                employee_id=form.employee_id.data,
                name=form.name.data,
                user_id=user_id,
            )
            db.session.add(emp)
            db.session.commit()
            flash(f"员工 {emp.name} 添加成功。", "success")
        return redirect(
            url_for("employees", include_resigned="1" if include_resigned else "0")
        )

    query = _employee_queryset()
    if not include_resigned:
        query = query.filter(Employee.is_resigned.is_(False))
    employee_list = query.order_by(Employee.employee_id).all()

    return render_template(
        "employees.html.jinja",
        employees=employee_list,
        form=form,
        include_resigned=include_resigned,
    )


@app.route("/employee/<int:employee_id>/resign", methods=["POST"])
@login_required
def employee_resign(employee_id):
    """Mark an employee as resigned after checking for outstanding tool holdings."""
    if not current_user.can_manage_employees:
        flash("审核员无权办理离职。", "danger")
        return redirect(url_for("employees"))

    emp = db.session.get(Employee, employee_id)
    if not emp or not _check_employee_access(emp):
        return redirect(url_for("employees"))

    holdings = (
        EmployeeToolHolding.query.filter_by(employee_id=emp.id)
        .filter(EmployeeToolHolding.count > 0)
        .all()
    )
    if holdings:
        tool_url = url_for("tool_employee_detail", employee_id=emp.id)
        flash(
            f"员工 {emp.name} 还持有工具，请先归还工具后再办理离职。",
            "danger",
        )
        return redirect(tool_url)

    emp.is_resigned = True
    db.session.commit()
    flash(f"员工 {emp.name} 已标记为离职。", "success")
    return redirect(url_for("employees"))

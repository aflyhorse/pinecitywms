from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    SelectField,
    IntegerField,
    DecimalField,
    FieldList,
    FormField,
    HiddenField,
    FileField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Length,
    EqualTo,
    ValidationError,
)


class LoginForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(1, 20)])
    password = PasswordField("密码", validators=[DataRequired(), Length(1, 40)])
    remember = BooleanField("保持登录", default="checked")
    submit = SubmitField("登录")


class ItemSearchForm(FlaskForm):
    name = StringField(
        "物品名称",
        render_kw={
            "placeholder": "物品名称",
            "list": "item-names",
            "autocomplete": "off",
        },
    )
    brand = StringField("品牌", render_kw={"placeholder": "品牌"})
    spec = StringField("规格", render_kw={"placeholder": "规格"})
    sku_id = StringField(
        "物料编号",
        render_kw={
            "placeholder": "物料编号",
            "autocomplete": "off",
        },
    )
    submit = SubmitField("搜索")


class ItemCreateForm(FlaskForm):
    item_name = StringField(
        "物品名称",
        validators=[DataRequired(), Length(1, 30)],
        render_kw={"list": "existing-items", "placeholder": "输入或双击选择物品"},
    )
    brand = StringField(
        "品牌",
        validators=[DataRequired(), Length(1, 30)],
        render_kw={"placeholder": "若没有品牌，填写'无'"},
    )
    spec = StringField(
        "规格",
        validators=[DataRequired(), Length(1, 50)],
        render_kw={"placeholder": "若没有规格，填写'通用'"},
    )
    submit = SubmitField("添加")


class StockInItemForm(FlaskForm):
    item_sku_id = HiddenField("物料编号")  # Hidden field for the actual item SKU ID
    item_sku_display = StringField(
        "物料编号",
        render_kw={
            "placeholder": "物料编号",
            "autocomplete": "off",
        },
    )
    item_id = StringField(
        "物品",
        validators=[InputRequired()],
        render_kw={
            "list": "item-ids",
            "autocomplete": "off",  # Disable browser's native autocomplete
        },
    )
    quantity = IntegerField("数量", validators=[InputRequired()])
    price = DecimalField("单价", validators=[InputRequired()])


class StockInForm(FlaskForm):
    refcode = StringField("入库单号", validators=[InputRequired(), Length(1, 30)])
    warehouse = SelectField("库房", coerce=int, validators=[InputRequired()])
    items = FieldList(FormField(StockInItemForm), min_entries=1)
    submit = SubmitField("入库")


class BatchStockInForm(FlaskForm):
    warehouse = SelectField("库房", coerce=int, validators=[InputRequired()])
    file = FileField("选择文件", validators=[InputRequired()])
    submit = SubmitField("上传")


class StockOutItemForm(FlaskForm):
    item_sku_id = HiddenField("物料编号")  # Hidden field for the actual item SKU ID
    item_sku_display = StringField(
        "物料编号",
        render_kw={
            "placeholder": "物料编号",
            "autocomplete": "off",
        },
    )
    item_id = StringField(
        "物品", validators=[InputRequired()], render_kw={"list": "item-ids"}
    )
    stock_count = IntegerField("库存数量", render_kw={"readonly": True})
    quantity = IntegerField("数量", validators=[InputRequired()])
    price = DecimalField(
        "单价", validators=[InputRequired()], render_kw={"readonly": True}
    )


class StockOutForm(FlaskForm):
    warehouse = SelectField("仓库", coerce=int, validators=[InputRequired()])
    area = SelectField(
        "区域",
        coerce=int,
        validators=[InputRequired()],
        render_kw={
            "data-placeholder": "请选择区域",
            "class": "select-with-placeholder",
        },
    )
    department = SelectField(
        "部门",
        coerce=int,
        validators=[InputRequired()],
        render_kw={
            "data-placeholder": "请选择部门",
            "class": "select-with-placeholder",
        },
    )
    location = StringField(
        "具体地点",
        validators=[InputRequired(), Length(1, 30)],
        render_kw={"placeholder": "必填：如1602，老干部大学走廊，5F茶水间等"},
    )
    note = StringField(
        "备注",
        validators=[Length(0, 100)],
        render_kw={"placeholder": "选填：其他涉及具体位置/部件的说明"},
    )
    items = FieldList(FormField(StockOutItemForm), min_entries=1)
    submit = SubmitField("出库")


class BatchTakeStockForm(FlaskForm):
    warehouse = SelectField("仓库", validators=[InputRequired()], coerce=int)
    file = FileField("文件", validators=[InputRequired()])
    note = StringField("说明", validators=[InputRequired()])
    submit = SubmitField("上传盘库文件")


class PasswordChangeForm(FlaskForm):
    username = SelectField("用户名", validators=[DataRequired()])
    old_password = PasswordField("原密码")  # Optional for admin
    new_password = PasswordField("新密码", validators=[DataRequired(), Length(1, 40)])
    confirm_password = PasswordField(
        "确认新密码",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="两次输入的密码必须相同"),
        ],
    )
    submit = SubmitField("修改密码")

    def validate_username(self, field):
        from flask_login import current_user

        if not current_user.is_admin and field.data != current_user.username:
            raise ValidationError("您只能修改自己的密码。")


class AccountCreateForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(1, 20)])
    nickname = StringField("昵称/班组名", validators=[DataRequired(), Length(1, 20)])
    role = SelectField(
        "权限",
        choices=[("user", "用户"), ("auditor", "审核员"), ("admin", "管理员")],
        validators=[DataRequired()],
    )
    password = PasswordField("初始密码", validators=[DataRequired(), Length(1, 40)])
    confirm_password = PasswordField(
        "确认密码",
        validators=[
            DataRequired(),
            EqualTo("password", message="两次输入的密码必须相同"),
        ],
    )
    submit = SubmitField("创建账户")


class RevokeReceiptForm(FlaskForm):
    reason = TextAreaField(
        "撤销原因", validators=[DataRequired(), Length(1, 200)], render_kw={"rows": "3"}
    )
    submit = SubmitField("撤销单据")


class EmployeeCreateForm(FlaskForm):
    employee_id = StringField(
        "工号",
        validators=[DataRequired(), Length(1, 20)],
        render_kw={"placeholder": "工号"},
    )
    name = StringField(
        "姓名",
        validators=[DataRequired(), Length(1, 30)],
        render_kw={"placeholder": "姓名"},
    )
    user_id = SelectField("所属班组", coerce=int, validators=[InputRequired()])
    submit = SubmitField("新增员工")


class ToolRequisitionForm(FlaskForm):
    """Select employee and submit tool requisition."""

    employee_id = SelectField("选择员工", coerce=int, validators=[InputRequired()])
    submit = SubmitField("领用")


class ToolReturnForm(FlaskForm):
    """Select action type for tool return / exchange."""

    action = SelectField(
        "操作",
        choices=[("return", "归还"), ("exchange", "更换")],
        validators=[InputRequired()],
    )
    submit = SubmitField("确认")

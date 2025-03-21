from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    RadioField,
    SelectField,
    IntegerField,
    DecimalField,
    FieldList,
    FormField,
    HiddenField,
    FileField,
)
from wtforms.validators import DataRequired, InputRequired, Length


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
    submit = SubmitField("搜索")


class ItemCreateForm(FlaskForm):
    item_choice = RadioField(
        "选择物品",
        choices=[("existing", "选择已有物品"), ("new", "创建新物品")],
        validators=[DataRequired()],
        default="new",
    )
    existing_item = StringField(
        "已有物品",
        render_kw={"list": "existing-items", "placeholder": "输入或双击选择物品"},
    )
    new_item_name = StringField("新物品名称")
    brand = StringField(
        "品牌",
        validators=[DataRequired(), Length(1, 20)],
        render_kw={"placeholder": "若没有品牌，填写'无'"},
    )
    spec = StringField(
        "规格",
        validators=[DataRequired(), Length(1, 20)],
        render_kw={"placeholder": "若没有规格，填写'通用'"},
    )
    submit = SubmitField("添加")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if self.item_choice.data == "existing" and not self.existing_item.data:
            self.existing_item.errors.append("请选择一个物品")
            return False
        if self.item_choice.data == "new" and not self.new_item_name.data:
            self.new_item_name.errors.append("请输入物品名称")
            return False
        return True


class StockInItemForm(FlaskForm):
    item_sku_id = HiddenField("物品ID")  # Hidden field for the actual item SKU ID
    item_id = StringField(
        "物品", validators=[DataRequired()], render_kw={"list": "item-ids"}
    )
    quantity = IntegerField("数量", validators=[InputRequired()])
    price = DecimalField("单价", validators=[InputRequired()])


class StockInForm(FlaskForm):
    refcode = StringField("入库单号", validators=[DataRequired(), Length(1, 30)])
    warehouse = SelectField("库房", coerce=int, validators=[InputRequired()])
    items = FieldList(FormField(StockInItemForm), min_entries=1)
    submit = SubmitField("入库")


class BatchStockInForm(FlaskForm):
    warehouse = SelectField("库房", coerce=int, validators=[InputRequired()])
    file = FileField("选择文件", validators=[DataRequired()])
    submit = SubmitField("上传")


class StockOutItemForm(FlaskForm):
    item_sku_id = HiddenField("物品ID")  # Hidden field for the actual item SKU ID
    item_id = StringField(
        "物品", validators=[DataRequired()], render_kw={"list": "item-ids"}
    )
    stock_count = IntegerField("库存数量", render_kw={"readonly": True})
    quantity = IntegerField("数量", validators=[InputRequired()])
    price = DecimalField(
        "单价", validators=[InputRequired()], render_kw={"readonly": True}
    )


class StockOutForm(FlaskForm):
    warehouse = SelectField("仓库", coerce=int, validators=[InputRequired()])
    area = SelectField("区域", coerce=int, validators=[InputRequired()])
    department = SelectField("部门", coerce=int, validators=[InputRequired()])
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
    warehouse = SelectField("仓库", validators=[DataRequired()], coerce=int)
    file = FileField("文件", validators=[DataRequired()])
    note = StringField("说明", validators=[DataRequired()])
    submit = SubmitField("上传盘库文件")

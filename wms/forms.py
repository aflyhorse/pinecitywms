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
)
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(1, 20)])
    password = PasswordField("密码", validators=[DataRequired(), Length(1, 40)])
    remember = BooleanField("保持登录", default="checked")
    submit = SubmitField("登录")


class ItemSearchForm(FlaskForm):
    name = StringField("物品名称", render_kw={"placeholder": "物品名称"})
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
        render_kw={"list": "existing-items", "placeholder": "输入或选择物品"},
    )
    new_item_name = StringField("新物品名称")
    brand = StringField("品牌", validators=[DataRequired(), Length(1, 20)])
    spec = StringField("规格", validators=[DataRequired(), Length(1, 20)])
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
    item_id = StringField(
        "物品", validators=[DataRequired()], render_kw={"list": "item-ids"}
    )
    quantity = IntegerField("数量", validators=[DataRequired()])
    price = DecimalField("价格", validators=[DataRequired()])


class StockInForm(FlaskForm):
    refcode = StringField("入库单号", validators=[DataRequired(), Length(1, 30)])
    warehouse = SelectField("库房", coerce=int, validators=[DataRequired()])
    items = FieldList(FormField(StockInItemForm), min_entries=1)
    submit = SubmitField("入库")

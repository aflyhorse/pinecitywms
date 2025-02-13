from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
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

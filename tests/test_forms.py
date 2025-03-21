from wms import app
from wms.forms import LoginForm, ItemSearchForm, ItemCreateForm


def test_login_form_validation():
    with app.test_request_context():
        # Test valid form
        form = LoginForm(
            meta={"csrf": False},
            data={"username": "testuser", "password": "password123", "remember": True},
        )
        assert form.validate() is True

        # Test missing username
        form = LoginForm(
            meta={"csrf": False}, data={"password": "password123", "remember": True}
        )
        assert form.validate() is False
        assert "This field is required." in form.username.errors

        # Test missing password
        form = LoginForm(
            meta={"csrf": False}, data={"username": "testuser", "remember": True}
        )
        assert form.validate() is False
        assert "This field is required." in form.password.errors

        # Test username too long
        form = LoginForm(
            meta={"csrf": False},
            data={
                "username": "a" * 21,  # Max length is 20
                "password": "password123",
                "remember": True,
            },
        )
        assert form.validate() is False
        assert "Field must be between 1 and 20 characters long." in form.username.errors


def test_item_search_form():
    with app.test_request_context():
        # Test empty form (should be valid as all fields are optional)
        form = ItemSearchForm(meta={"csrf": False}, data={})
        assert form.validate() is True

        # Test with valid data
        form = ItemSearchForm(
            meta={"csrf": False},
            data={"name": "Test Item", "brand": "Test Brand", "spec": "Test Spec"},
        )
        assert form.validate() is True

        # Test with partial data
        form = ItemSearchForm(meta={"csrf": False}, data={"name": "Test Item"})
        assert form.validate() is True


def test_item_create_form():
    with app.test_request_context():
        # Test new item creation with detailed debugging
        data = {
            "item_name": "New Item",
            "brand": "Test Brand",
            "spec": "Test Spec",
        }
        print(f"Input data: {data}")

        form = ItemCreateForm(
            meta={"csrf": False},
            data=data,
        )

        # Print form field data
        print("Form data received:")
        for field_name, field in form._fields.items():
            print(f"  {field_name}: {field.data}")

        # Debug: Print validation errors if any
        if not form.validate():
            print("Form validation errors:")
            for field_name, errors in form.errors.items():
                print(f"  {field_name}: {errors}")

        assert form.validate() is True

        # Test existing item selection
        form = ItemCreateForm(
            meta={"csrf": False},
            data={
                "item_name": "Test Item",
                "brand": "Test Brand",
                "spec": "Test Spec",
            },
        )
        assert form.validate() is True

        # Test invalid form - missing new item name
        form = ItemCreateForm(
            meta={"csrf": False},
            data={"brand": "Test Brand", "spec": "Test Spec"},
        )
        assert form.validate() is False

        # Test invalid form - missing brand
        form = ItemCreateForm(
            meta={"csrf": False},
            data={
                "item_name": "New Item",
                "spec": "Test Spec",
            },
        )
        assert form.validate() is False
        assert "This field is required." in form.brand.errors

        # Test invalid form - missing spec
        form = ItemCreateForm(
            meta={"csrf": False},
            data={
                "item_name": "New Item",
                "brand": "Test Brand",
            },
        )
        assert form.validate() is False
        assert "This field is required." in form.spec.errors

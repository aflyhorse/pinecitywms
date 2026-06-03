from wms import app, db
from wms.models import Area, Department, User, Warehouse
from wms.settings import sync_initial_reference_data


def test_index_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.location


def test_index_authenticated(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 302  # Now redirects to inventory
    assert "/inventory" in response.location


def test_site_name_loaded_from_config(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert app.config["SITE_NAME"].encode() in response.data


def test_initial_seed_uses_configured_reference_data(client):
    with app.app_context():
        assert sync_initial_reference_data() is True

        usernames = [user.username for user in User.query.order_by(User.username).all()]
        assert usernames == ["admin"]

        admin = User.query.filter_by(username="admin").one()
        assert admin.is_admin is True
        assert admin.warehouse is not None
        assert admin.warehouse.name == "办公室仓库"

        recycle = Warehouse.query.filter_by(name="回收仓库").one()
        assert recycle.is_public is True


def test_reference_data_sync_only_adds_missing_areas_and_departments(client):
    with app.app_context():
        db.create_all()
        db.session.add_all([Area(name="历史区域"), Department(name="历史部门")])
        db.session.commit()

        before_area_names = {area.name for area in Area.query.all()}
        before_department_names = {
            department.name for department in Department.query.all()
        }

        assert sync_initial_reference_data() is True

        after_area_names = {area.name for area in Area.query.all()}
        after_department_names = {
            department.name for department in Department.query.all()
        }

        assert "历史区域" in after_area_names
        assert "历史部门" in after_department_names
        assert before_area_names.issubset(after_area_names)
        assert before_department_names.issubset(after_department_names)
        assert len(after_area_names) >= len(before_area_names)
        assert len(after_department_names) >= len(before_department_names)

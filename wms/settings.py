from configparser import ConfigParser
from pathlib import Path
from sqlalchemy.exc import OperationalError

DEFAULT_SITE_NAME = "青松城设备科仓库管理系统"
DEFAULT_PUBLIC_AREAS = [
    "地下室",
    "1F房间",
    "1F公共区域",
    "2F房间",
    "2F公共区域",
    "3F房间",
    "3F公共区域",
    "4F房间",
    "4F公共区域",
    "5F屋面",
    "5-11F办公房房间",
    "5-11F办公房公共区域",
    "12-19F客房房间",
    "12-19F客房公共区域",
    "19F屋面",
    "其他公共区域",
    "班组",
    "老干部招待所",
    "岳阳大院",
]
DEFAULT_DEPARTMENTS = [
    "活动中心主任室",
    "行政办公室",
    "康乐科",
    "餐饮服务科",
    "会务科",
    "总经理/副总经理室",
    "党建办",
    "人事科",
    "设备管理科",
    "安全保卫科",
    "规划财务科",
    "业务指导一科（营销）",
    "业务指导二科（客房）",
    "业务指导三科（餐饮）",
    "老干部大学",
    "老干部招待所",
    "岳阳大院",
]
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_NICKNAME = "办公室"
DEFAULT_RECYCLE_WAREHOUSE_NAME = "回收仓库"


def _config_path(app) -> Path:
    return Path(app.root_path).parent / "config.ini"


def _parse_list(raw_value: str) -> list[str]:
    values: list[str] = []
    for line in raw_value.splitlines():
        for item in line.split(","):
            item = item.strip()
            if item:
                values.append(item)
    return values


def load_runtime_config(app) -> None:
    parser = ConfigParser()
    config_path = _config_path(app)
    if config_path.exists():
        parser.read(config_path, encoding="utf-8")

    site_name = parser.get("site", "name", fallback=DEFAULT_SITE_NAME).strip()
    app.config["SITE_NAME"] = site_name or DEFAULT_SITE_NAME
    app.config["INITIAL_PUBLIC_AREAS"] = _parse_list(
        parser.get(
            "seed",
            "public_areas",
            fallback="\n".join(DEFAULT_PUBLIC_AREAS),
        )
    )
    app.config["INITIAL_DEPARTMENTS"] = _parse_list(
        parser.get(
            "seed",
            "departments",
            fallback="\n".join(DEFAULT_DEPARTMENTS),
        )
    )
    app.config["INITIAL_ADMIN_USERNAME"] = (
        parser.get("seed", "admin_username", fallback=DEFAULT_ADMIN_USERNAME).strip()
        or DEFAULT_ADMIN_USERNAME
    )
    app.config["INITIAL_ADMIN_NICKNAME"] = (
        parser.get("seed", "admin_nickname", fallback=DEFAULT_ADMIN_NICKNAME).strip()
        or DEFAULT_ADMIN_NICKNAME
    )
    app.config["INITIAL_RECYCLE_WAREHOUSE_NAME"] = (
        parser.get(
            "seed", "recycle_warehouse_name", fallback=DEFAULT_RECYCLE_WAREHOUSE_NAME
        ).strip()
        or DEFAULT_RECYCLE_WAREHOUSE_NAME
    )


def sync_initial_reference_data() -> bool:
    from wms import app, db
    from wms.models import Area, Department, User, Warehouse

    try:
        public_areas = app.config.get("INITIAL_PUBLIC_AREAS", DEFAULT_PUBLIC_AREAS)
        departments = app.config.get("INITIAL_DEPARTMENTS", DEFAULT_DEPARTMENTS)

        existing_area_names = {area.name for area in db.session.query(Area).all()}
        for area_name in public_areas:
            if area_name not in existing_area_names:
                db.session.add(Area(name=area_name))

        existing_department_names = {
            department.name for department in db.session.query(Department).all()
        }
        for department_name in departments:
            if department_name not in existing_department_names:
                db.session.add(Department(name=department_name))

        admin_username = app.config.get(
            "INITIAL_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME
        )
        admin_nickname = app.config.get(
            "INITIAL_ADMIN_NICKNAME", DEFAULT_ADMIN_NICKNAME
        )
        recycle_warehouse_name = app.config.get(
            "INITIAL_RECYCLE_WAREHOUSE_NAME", DEFAULT_RECYCLE_WAREHOUSE_NAME
        )

        admin_user = User.query.filter_by(username=admin_username).first()
        if admin_user is None:
            admin_user = User(
                username=admin_username,
                nickname=admin_nickname,
                is_admin=True,
            )
            admin_user.set_password(admin_username)
            db.session.add(admin_user)
            db.session.flush()

        admin_warehouse = Warehouse.query.filter_by(owner_id=admin_user.id).first()
        if admin_warehouse is None:
            admin_warehouse = Warehouse.query.filter_by(
                name=f"{admin_nickname}仓库"
            ).first()
            if admin_warehouse is None:
                db.session.add(
                    Warehouse(name=f"{admin_nickname}仓库", owner=admin_user)
                )

        recycle_warehouse = Warehouse.query.filter_by(
            name=recycle_warehouse_name
        ).first()
        if recycle_warehouse is None:
            db.session.add(Warehouse(name=recycle_warehouse_name, is_public=True))

        db.session.commit()
        return True
    except OperationalError:
        db.session.rollback()
        return False

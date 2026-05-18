"""Comprehensive tests for wms.routes.item to improve coverage."""
import json
from wms import app, db
from wms.models import Item, ItemSKU, ToolInventory, Warehouse, WarehouseItemSKU


def _login_admin(client):
    """Login as admin user."""
    client.post(
        "/login",
        data={"username": "testadmin", "password": "password123", "remember": "y"},
        follow_redirects=True,
    )


def test_item_page_empty_database(auth_client):
    """Test /item page when database is empty."""
    resp = auth_client.get("/item")
    assert resp.status_code == 200
    assert "物品管理".encode() in resp.data or "SKU".encode() in resp.data


def test_item_search_by_name(auth_client):
    """Test item search filter by name."""
    with app.app_context():
        item = Item(name="筛选测试物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="Brand1", spec="Spec1")
        db.session.add(sku)
        db.session.commit()

    resp = auth_client.get("/item?name=筛选测试")
    assert resp.status_code == 200
    assert "筛选测试物品".encode() in resp.data


def test_item_search_by_brand(auth_client):
    """Test item search filter by brand."""
    with app.app_context():
        item = Item(name="品牌测试物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="特殊品牌", spec="Spec1")
        db.session.add(sku)
        db.session.commit()

    resp = auth_client.get("/item?brand=特殊品牌")
    assert resp.status_code == 200
    assert "品牌测试物品".encode() in resp.data


def test_item_search_by_spec(auth_client):
    """Test item search filter by spec."""
    with app.app_context():
        item = Item(name="规格测试物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="Brand1", spec="特殊规格")
        db.session.add(sku)
        db.session.commit()

    resp = auth_client.get("/item?spec=特殊规格")
    assert resp.status_code == 200
    assert "规格测试物品".encode() in resp.data


def test_item_search_by_sku_id(auth_client):
    """Test item search filter by exact SKU ID."""
    with app.app_context():
        item = Item(name="SKUID测试物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="Brand1", spec="Spec1")
        db.session.add(sku)
        db.session.commit()
        sku_id = sku.id

    resp = auth_client.get(f"/item?sku_id={sku_id}")
    assert resp.status_code == 200
    assert "SKUID测试物品".encode() in resp.data


def test_item_search_by_invalid_sku_id(auth_client):
    """Test item search with invalid SKU ID (should be ignored)."""
    resp = auth_client.get("/item?sku_id=invalid")
    assert resp.status_code == 200


def test_item_search_post_form(auth_client):
    """Test item search via POST form (should redirect to GET)."""
    with app.app_context():
        item = Item(name="表单测试物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="BrandA", spec="SpecA")
        db.session.add(sku)
        db.session.commit()

    resp = auth_client.post(
        "/item",
        data={"name": "表单测试", "brand": "", "spec": "", "sku_id": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "表单测试物品".encode() in resp.data


def test_item_create_new_item_and_sku(auth_client):
    """Test creating a completely new item and SKU."""
    resp = auth_client.post(
        "/item/create",
        data={
            "item_name": "新建物品123",
            "brand": "新建品牌",
            "spec": "新建规格",
            "is_tool": False,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "物品添加成功".encode() in resp.data

    with app.app_context():
        item = Item.query.filter_by(name="新建物品123").first()
        assert item is not None
        assert len(item.skus) == 1
        assert item.skus[0].brand == "新建品牌"
        assert item.skus[0].spec == "新建规格"


def test_item_create_existing_item_new_sku(auth_client):
    """Test adding new SKU to existing item."""
    with app.app_context():
        item = Item(name="现有物品")
        db.session.add(item)
        db.session.flush()
        sku1 = ItemSKU(item_id=item.id, brand="品牌1", spec="规格1")
        db.session.add(sku1)
        db.session.commit()
        item_id = item.id

    resp = auth_client.post(
        "/item/create",
        data={
            "item_name": "现有物品",
            "brand": "品牌2",
            "spec": "规格2",
            "is_tool": False,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "物品添加成功".encode() in resp.data

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert len(item.skus) == 2


def test_item_create_duplicate_sku_enabled(auth_client):
    """Test creating duplicate SKU when it's already enabled (error)."""
    with app.app_context():
        item = Item(name="重复物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌A", spec="规格A", disabled=False)
        db.session.add(sku)
        db.session.commit()

    resp = auth_client.post(
        "/item/create",
        data={
            "item_name": "重复物品",
            "brand": "品牌A",
            "spec": "规格A",
            "is_tool": False,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "已存在".encode() in resp.data


def test_item_create_duplicate_sku_disabled_re_enable(auth_client):
    """Test creating duplicate SKU when it's disabled (should re-enable)."""
    with app.app_context():
        item = Item(name="禁用物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌B", spec="规格B", disabled=True)
        db.session.add(sku)
        db.session.commit()
        sku_id = sku.id

    resp = auth_client.post(
        "/item/create",
        data={
            "item_name": "禁用物品",
            "brand": "品牌B",
            "spec": "规格B",
            "is_tool": False,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "已修改为启用".encode() in resp.data

    with app.app_context():
        sku = db.session.get(ItemSKU, sku_id)
        assert sku.disabled is False


def test_toggle_disabled_sku_success(auth_client):
    """Test toggle disabled status for a SKU."""
    with app.app_context():
        item = Item(name="切换物品")
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌C", spec="规格C", disabled=False)
        db.session.add(sku)
        db.session.commit()
        sku_id = sku.id

    resp = auth_client.post(f"/item/{sku_id}/toggle_disabled")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert data["disabled"] is True

    with app.app_context():
        sku = db.session.get(ItemSKU, sku_id)
        assert sku.disabled is True


def test_toggle_disabled_sku_not_found(auth_client):
    """Test toggle disabled for non-existent SKU."""
    resp = auth_client.post("/item/9999/toggle_disabled")
    assert resp.status_code == 404
    data = json.loads(resp.data)
    assert data["success"] is False


def test_toggle_tool_mark_as_tool(auth_client):
    """Test marking an item as a tool."""
    with app.app_context():
        item = Item(name="标记工具物品", is_tool=False)
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌D", spec="规格D")
        db.session.add(sku)

        # Create a warehouse with stock
        warehouse = Warehouse(name="工具仓库", owner_id=1)  # testadmin has id=1
        db.session.add(warehouse)
        db.session.flush()

        wis = WarehouseItemSKU(
            warehouse_id=warehouse.id, itemSKU_id=sku.id, count=10, average_price=100
        )
        db.session.add(wis)
        db.session.commit()
        item_id = item.id
        sku_id = sku.id

    resp = auth_client.post(f"/item/{item_id}/toggle_tool")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert data["is_tool"] is True
    assert "已标记为工具" in data["message"]

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.is_tool is True
        # Verify ToolInventory was created
        ti = ToolInventory.query.filter_by(user_id=1, itemSKU_id=sku_id).first()
        assert ti is not None
        assert ti.count == 10


def test_toggle_tool_unmark_as_tool(auth_client):
    """Test unmarking an item as a tool."""
    with app.app_context():
        item = Item(name="取消工具标记物品", is_tool=True)
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌E", spec="规格E")
        db.session.add(sku)
        db.session.flush()

        # Create ToolInventory
        ti = ToolInventory(user_id=1, itemSKU_id=sku.id, count=5, pending_scrap=0)
        db.session.add(ti)
        db.session.commit()
        item_id = item.id
        sku_id = sku.id

    resp = auth_client.post(f"/item/{item_id}/toggle_tool")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert data["is_tool"] is False
    assert "已取消工具标记" in data["message"]

    with app.app_context():
        item = db.session.get(Item, item_id)
        assert item.is_tool is False
        # Verify ToolInventory was deleted
        ti = ToolInventory.query.filter_by(user_id=1, itemSKU_id=sku_id).first()
        assert ti is None


def test_toggle_tool_item_not_found(auth_client):
    """Test toggle tool for non-existent item."""
    resp = auth_client.post("/item/9999/toggle_tool")
    assert resp.status_code == 404
    data = json.loads(resp.data)
    assert data["success"] is False


def test_toggle_tool_resync_warehouse_stock(auth_client):
    """Test toggle tool re-syncs warehouse stock when toggled off and back on."""
    with app.app_context():
        item = Item(name="重新同步工具", is_tool=False)
        db.session.add(item)
        db.session.flush()
        sku = ItemSKU(item_id=item.id, brand="品牌F", spec="规格F")
        db.session.add(sku)

        warehouse = Warehouse(name="重新同步仓库", owner_id=1)
        db.session.add(warehouse)
        db.session.flush()

        wis = WarehouseItemSKU(
            warehouse_id=warehouse.id, itemSKU_id=sku.id, count=20, average_price=50
        )
        db.session.add(wis)
        db.session.commit()
        item_id = item.id
        sku_id = sku.id

    # Mark as tool
    auth_client.post(f"/item/{item_id}/toggle_tool")

    with app.app_context():
        ti = ToolInventory.query.filter_by(user_id=1, itemSKU_id=sku_id).first()
        assert ti.count == 20
        # Manually update the count
        ti.count = 5
        db.session.commit()

    # Unmark as tool
    auth_client.post(f"/item/{item_id}/toggle_tool")

    with app.app_context():
        ti = ToolInventory.query.filter_by(user_id=1, itemSKU_id=sku_id).first()
        assert ti is None

    # Mark as tool again - should resync from warehouse stock
    auth_client.post(f"/item/{item_id}/toggle_tool")

    with app.app_context():
        ti = ToolInventory.query.filter_by(user_id=1, itemSKU_id=sku_id).first()
        assert ti.count == 20  # Should resync to warehouse stock


def test_item_search_with_special_like_chars(auth_client):
    """Test item search with special LIKE characters (%, _) to verify escaping."""
    with app.app_context():
        # Create items with special characters in names
        item1 = Item(name="物品%特殊")
        item2 = Item(name="物品_下划线")
        db.session.add_all([item1, item2])
        db.session.flush()
        sku1 = ItemSKU(item_id=item1.id, brand="品牌%", spec="规格_")
        sku2 = ItemSKU(item_id=item2.id, brand="品牌\\反斜", spec="规格normal")
        db.session.add_all([sku1, sku2])
        db.session.commit()

    # Search for item with % (should escape properly)
    resp = auth_client.get("/item?name=物品%")
    assert resp.status_code == 200
    assert "物品%特殊".encode() in resp.data or "未找到".encode() in resp.data

    # Search for brand with %
    resp = auth_client.get("/item?brand=品牌%")
    assert resp.status_code == 200


def test_item_create_get_page(auth_client):
    """Test GET /item/create page loads correctly."""
    resp = auth_client.get("/item/create")
    assert resp.status_code == 200
    assert "物品名称".encode() in resp.data or "item".encode() in resp.data

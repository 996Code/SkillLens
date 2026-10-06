"""P2 交互画像指纹自动生成：从系统页面 DOM 指纹识别组件库/交互家族——
生成画像草稿（新系统接入零手写画像）。"""
from app.adapters.fingerprint import fingerprint_page, detect_profile


def test_ant_design_detection():
    dom = """
    <div class="ant-modal-content"><button class="ant-btn ant-btn-primary">保存</button></div>
    <ul class="ant-dropdown-menu"><li class="ant-dropdown-menu-item">同步数据库</li></ul>
    <form class="ant-form-item"><label>*表名</label><input/></form>
    <table><tr class="ant-table-row"><td>更多</td></tr></table>
    """
    fp = fingerprint_page(dom, url="http://127.0.0.1:8095/online/cgform")
    assert fp["ui_library"] == "ant-design"
    profile = detect_profile(fp)
    assert profile.dropdown.engine == "ant-design"
    assert profile.dropdown.menu_item_match == "includes"
    assert profile.modal_submit.pick == "last_visible"


def test_element_plus_detection():
    dom = """
    <div class="el-dropdown"><span class="user-nickname">若依</span></div>
    <ul><li class="el-dropdown-menu__item">退出登录</li></ul>
    <div class="el-message-box"><button>确 定</button></div>
    """
    fp = fingerprint_page(dom, url="http://127.0.0.1:8093/index")
    assert fp["ui_library"] == "element-plus"
    profile = detect_profile(fp)
    assert profile.dropdown.engine == "element-plus"


def test_frappe_detection():
    dom = """
    <div class="frappe-control" data-fieldname="party_name"><input/></div>
    <button data-label="Save">Save</button>
    <form><div class="modal-content"></div></form>
    """
    fp = fingerprint_page(dom, url="http://127.0.0.1:8090/app/quotation/new")
    assert fp["framework"] == "frappe"
    profile = detect_profile(fp)
    assert profile.form_fill.framework == "frappe"
    assert profile.route_guard.async_set_route is True


def test_generic_fallback():
    dom = "<form><label>标题</label><input name='title'/></form>"
    fp = fingerprint_page(dom, url="http://127.0.0.1:8082/index.php")
    profile = detect_profile(fp)
    assert profile.dropdown.engine == "generic"
    assert "name-attr" in profile.form_fill.field_locators


async def test_fingerprint_api(client):
    """指纹 API：dom → profile_yaml 片段（向导 UI 消费）。"""
    r = await client.post("/api/v1/adapters/fingerprint", json={
        "dom": '<div class="ant-modal-content"><button>保存</button></div>',
        "url": "http://x/y"})
    assert r.status_code == 200
    body = r.json()
    assert body["fingerprint"]["ui_library"] == "ant-design"
    assert "interaction_profile" in body["profile_yaml"]

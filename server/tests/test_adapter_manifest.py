"""AF1 适配器 manifest schema+loader（TDD：docs/specs 主计划块 AF；schema 三原则）。

校验语义：
- id/target.base_url 必填；credentials.password_env 与 password_literal 互斥，
  password_literal（仅限本地演示容器）产生 lint 警告——安全红线（HANDOVER §5.4）；
- login.steps 是 6 原语微 DSL：goto/fill/click/select/wait/routine（未知原语拒）；
- probes.kind ∈ {docker-exec, http}；http 探针 assert 可含 status/contains；
- flows/chains 可选（设计原则③：flows 缺省=人工走查模式）；
- loader：目录扫描 adapters/*.yaml → 逐份校验 → {manifests, lints}。
"""
from pathlib import Path

import pytest

from app.adapters.manifest import (
    load_manifest_text,
    load_adapter_dir,
    ManifestLint,
)

ZENTAO_MIN = """
id: zentao
label: 禅道 22
target:
  base_url: http://127.0.0.1:8082
credentials:
  username: admin
  password_env: ZENTAO_PW
login:
  steps:
    - goto: /index.php?m=user&f=login
    - fill: ["#account", "${username}"]
    - fill: ["input[name=password]", "${password}"]
    - click: "button[type=submit], #submit"
  post_login: [close_guide]
probes:
  - id: story_count
    kind: docker-exec
    container: zentao
    shell: 'mysql -uroot -p"$ZENTAO_PW" -N -e "SELECT COUNT(*) FROM zentao.zt_story"'
chains:
  - name: qa-chain
    rounds: 2
    skills: [ZentaoStoryCreate, ZentaoCaseRun]
    replay:
      - skill: ZentaoStoryCreate
        overrides: {"*标题": "SL回放${ts}"}
        verify: {probe: story_count, expect: increased}
"""


def test_minimal_manifest_valid():
    m, lints = load_manifest_text(ZENTAO_MIN)
    assert m.id == "zentao" and m.label == "禅道 22"
    assert m.credentials.password_env == "ZENTAO_PW"
    assert lints == []
    # 原语解释
    ops = [s.op for s in m.login.steps]
    assert ops == ["goto", "fill", "fill", "click"]
    assert m.login.post_login == ["close_guide"]
    assert m.probes[0].kind == "docker-exec"
    assert m.chains[0].replay[0].verify.expect == "increased"


def test_password_literal_lints_but_env_ok():
    base = ZENTAO_MIN.replace("password_env: ZENTAO_PW",
                              "password_literal: admin123")
    m, lints = load_manifest_text(base)
    assert m.credentials.password_literal == "admin123"
    assert any(l.code == "password_literal" for l in lints)
    # env 模式零警告
    m2, lints2 = load_manifest_text(ZENTAO_MIN)
    assert not any(l.code == "password_literal" for l in lints2)


def test_unknown_step_primitive_rejected():
    bad = ZENTAO_MIN.replace("    - goto: /index.php?m=user&f=login",
                             "    - hover: '#x'")
    with pytest.raises(Exception):
        load_manifest_text(bad)


def test_flows_optional_manual_mode():
    """设计原则③：flows 可缺省——接入退化为登录引导+人工走查+探针。"""
    no_flows = ZENTAO_MIN  # 本样例即无 flows
    m, _ = load_manifest_text(no_flows)
    assert m.flows in (None, [])


def test_http_probe_form():
    doc = ZENTAO_MIN.replace(
        """  - id: story_count
    kind: docker-exec
    container: zentao
    shell: 'mysql -uroot -p"$ZENTAO_PW" -N -e "SELECT COUNT(*) FROM zentao.zt_story"'""",
        """  - id: login_ok
    kind: http
    request: {method: POST, url: "${base_url}/prod-api/login",
              json: {username: "${new_user}", password: "${new_pass}"}}
    assert: {status: 200, contains: token}""")
    m, _ = load_manifest_text(doc)
    assert m.probes[0].kind == "http"
    assert m.probes[0].request.method == "POST"
    assert m.probes[0].probe_assert.contains == "token"


def test_load_adapter_dir_collects_and_lints(tmp_path: Path):
    d = tmp_path / "adapters"
    d.mkdir()
    (d / "zentao.yaml").write_text(ZENTAO_MIN, encoding="utf-8")
    bad = ZENTAO_MIN.replace("password_env: ZENTAO_PW",
                             "password_literal: admin123").replace(
        "id: zentao", "id: ruoyi")
    (d / "ruoyi.yaml").write_text(bad, encoding="utf-8")
    manifests, lints = load_adapter_dir(d)
    assert {m.id for m in manifests} == {"zentao", "ruoyi"}
    assert any(l.code == "password_literal" for l in lints)


def test_repo_seven_system_adapters_validate():
    """AF1 验收：仓库系统清单（s43 脚本机械提取）全部通过校验；
    env 模式系统（禅道/Odoo/Dolibarr）零 password_literal 警告。
    P4 后为 8 系统（+firefly——零代码接入终验的声明产物）。"""
    repo_adapters = Path(__file__).resolve().parent.parent / "adapters"
    manifests, lints = load_adapter_dir(repo_adapters)
    ids = {m.id for m in manifests}
    assert ids == {"zentao", "ruoyi", "jeecg", "snipe", "odoo",
                   "erpnext", "dolibarr", "firefly"}
    linted_files = {l.file for l in lints}
    assert linted_files <= {"ruoyi.yaml", "jeecg.yaml", "snipe.yaml",
                            "erpnext.yaml", "dolibarr.yaml", "zentao.yaml",
                            "odoo.yaml", "firefly.yaml"}
    for m in manifests:
        if m.id == "firefly":
            continue  # P4 终验清单（演示容器——无 probes/flows 精简声明）
        assert m.probes, f"{m.id} 无探针"
        assert m.chains, f"{m.id} 无业务链"


def test_interaction_profile_roundtrip():
    """P1 交互画像（平台化组件化）：dropdown/modal_submit/form_fill/row_action/
    route_guard 五维声明——执行器特化分支的声明式载体。"""
    doc = """
id: demo
label: 演示系统
target: {base_url: "http://t"}
credentials: {username: u, password_literal: p}
interaction_profile:
  dropdown:
    engine: ant-design
    menu_item_match: includes
    menu_item_click: trusted
    mount_wait_ms: 400
  modal_submit:
    selector: .ant-modal-content
    button_regex: '保存|确定|提\s*交|同步'
    pick: last_visible
    render_wait_ms: 800
  form_fill:
    framework: generic
    field_locators: [placeholder, form-item-label, name-attr]
    same_label_priority: modal_first
  row_action:
    anchor_match: insensitive
    scroll_into_view: true
  route_guard:
    async_set_route: true
    normalize_new_suffix: true
"""
    m, lints = load_manifest_text(doc)
    ip = m.interaction_profile
    assert ip is not None
    assert ip.dropdown.engine == "ant-design"
    assert ip.dropdown.menu_item_match == "includes"
    assert ip.dropdown.menu_item_click == "trusted"
    assert ip.modal_submit.pick == "last_visible"
    assert "placeholder" in ip.form_fill.field_locators
    assert ip.row_action.anchor_match == "insensitive"
    assert ip.route_guard.async_set_route is True


def test_interaction_profile_defaults():
    """无画像（存量 7 清单）——None 容错（执行器走通用默认）。"""
    doc = """
id: demo2
target: {base_url: "http://t"}
credentials: {username: u, password_literal: p}
"""
    m, _ = load_manifest_text(doc)
    assert m.interaction_profile is None


def test_interaction_profile_ao1_selector_externalization():
    """AO1（引擎零系统知识）：组件选择器上画像——引擎残留的 antd/
    element-plus/select2 硬编码选择器外置为声明字段。默认值=原引擎
    硬编码值（零画像零行为变化），系统可在 YAML 覆盖。"""
    doc = """
id: demo3
target: {base_url: "http://t"}
credentials: {username: u, password_literal: p}
interaction_profile:
  dropdown:
    menu_item_selector: '.my-menu-item'
  form_fill:
    container_selector: '.my-form-group, .my-form-item'
    control_selector: '.my-select-widget'
    validation_error_selector: '.my-field-error'
"""
    m, _ = load_manifest_text(doc)
    ip = m.interaction_profile
    assert ip.dropdown.menu_item_selector == ".my-menu-item"
    assert ip.form_fill.container_selector == ".my-form-group, .my-form-item"
    assert ip.form_fill.control_selector == ".my-select-widget"
    assert ip.form_fill.validation_error_selector == ".my-field-error"


def test_interaction_profile_ao1_defaults_match_engine_hardcoded():
    """AO1 默认值=引擎现硬编码值（向后兼容锚）——改引擎默认前先锁住
    现值，防止外置时默认值漂移改变无画像系统行为。"""
    doc = """
id: demo4
target: {base_url: "http://t"}
credentials: {username: u, password_literal: p}
interaction_profile:
  dropdown: {}
  form_fill: {}
"""
    m, _ = load_manifest_text(doc)
    ip = m.interaction_profile
    assert ip.dropdown.menu_item_selector == (
        ".ant-dropdown-menu-item, .el-dropdown-menu__item")
    assert ".form-group" in ip.form_fill.container_selector
    assert ".ant-form-item" in ip.form_fill.container_selector
    assert ".select2-container" in ip.form_fill.control_selector
    assert ".ant-form-item-explain-error" in ip.form_fill.validation_error_selector


def test_probe_container_rejects_option_injection():
    """评审三轮 #2：container 直入 docker CLI argv——`-` 开头会被 docker
    解析为选项（--user=0 → root 进容器），清单可由 reviewer 写盘 → 必须
    schema 层拒绝。"""
    for bad in ("--user=0", "-x", ".hidden"):
        doc = ZENTAO_MIN.replace("container: zentao", f"container: '{bad}'")
        with pytest.raises(Exception, match="container"):
            load_manifest_text(doc)


def test_probe_container_accepts_normal_names():
    for name in ("erpnext-mariadb-1", "odoo18_db_1", "a.b-c_1", "zentao"):
        doc = ZENTAO_MIN.replace("container: zentao", f"container: {name}")
        m, _ = load_manifest_text(doc)
        assert m.probes[0].container == name


def test_login_admin_nickname_parsed():
    """评审三轮 #4：steps.login 读 manifest.login.admin_nickname——模型缺
    字段时 pydantic extra=ignore 静默丢弃，身份校验分支永不触发（死代码）。"""
    doc = ZENTAO_MIN.replace("login:\n  steps:",
                             "login:\n  admin_nickname: 超级管理员\n  steps:")
    m, _ = load_manifest_text(doc)
    assert m.login.admin_nickname == "超级管理员"


def test_url_matches_with_query_lints():
    """评审三轮 #5b：匹配引擎按油猴语义剥离 query——模式含 `?` 永不命中，
    loader 必须产 lint 警示清单作者（不静默）。"""
    doc = ZENTAO_MIN + '\nurl_matches: ["http://127.0.0.1:8082/app?a=1"]\n'
    _, lints = load_manifest_text(doc)
    assert any(l.code == "url_match_query" for l in lints)
    # 无 query 的模式零警告
    doc2 = ZENTAO_MIN + '\nurl_matches: ["http://127.0.0.1:8082/*"]\n'
    _, lints2 = load_manifest_text(doc2)
    assert not any(l.code == "url_match_query" for l in lints2)


def test_load_adapter_dir_survives_bad_file(tmp_path: Path):
    """评审三轮 #6：单份坏 YAML 不得拖垮整个目录（GET /adapters 全 500）——
    降级为 lint 错误条目，健康清单照常返回。"""
    d = tmp_path / "ad"
    d.mkdir()
    (d / "good.yaml").write_text(ZENTAO_MIN, encoding="utf-8")
    (d / "bad.yaml").write_text("id: [unclosed\n  x: }\n", encoding="utf-8")
    manifests, lints = load_adapter_dir(d)
    assert [m.id for m in manifests] == ["zentao"]
    bad = [l for l in lints if l.file == "bad.yaml"]
    assert bad and bad[0].code == "parse_error"


class TestRedactManifestText:
    """评审三轮 #1：GET /adapters/{id}/yaml 原文回显清单——password_literal
    泄漏给所有登录用户（含 viewer）。redact_manifest_text 纯函数收口。"""

    def test_password_literal_masked(self):
        from app.adapters.manifest import redact_manifest_text
        doc = ('id: demo\ntarget: {base_url: "http://t"}\n'
               'credentials: {username: u, password_literal: "Sup3rS3cret"}\n')
        out = redact_manifest_text(doc)
        assert "Sup3rS3cret" not in out
        assert "***" in out
        assert "demo" in out and "username" in out

    def test_password_env_reference_not_masked(self):
        """password_env 存的是环境变量名（非秘密值）——脱敏会毁排障信息。"""
        from app.adapters.manifest import redact_manifest_text
        doc = ('id: demo\ntarget: {base_url: "http://t"}\n'
               'credentials: {username: u, password_env: DEMO_PW}\n')
        out = redact_manifest_text(doc)
        assert "DEMO_PW" in out

    def test_nested_sensitive_keys_masked(self):
        from app.adapters.manifest import redact_manifest_text
        doc = ('id: demo\ntarget: {base_url: "http://t"}\n'
               'credentials: {username: u, password_env: E}\n'
               'probes:\n'
               '  - id: p\n    kind: http\n'
               '    request: {method: POST, url: "http://t/x",\n'
               '              json: {api_key: AKIA-FAKE, token: tk-FAKE,'
               ' user: keepme}}\n')
        out = redact_manifest_text(doc)
        assert "AKIA-FAKE" not in out and "tk-FAKE" not in out
        assert "keepme" in out

    def test_unparseable_input_still_masked(self):
        """YAML 解析失败降级行级正则掩码——绝不原文返回。"""
        from app.adapters.manifest import redact_manifest_text
        text = 'credentials: {password_literal: "Sup3rS3cret", broken: [unclosed'
        out = redact_manifest_text(text)
        assert "Sup3rS3cret" not in out
        assert "***" in out

    def test_non_secret_keys_untouched(self):
        from app.adapters.manifest import redact_manifest_text
        doc = ZENTAO_MIN
        out = redact_manifest_text(doc)
        assert "zentao" in out and "ZENTAO_PW" in out
        assert "story_count" in out and "http://127.0.0.1:8082" in out


class TestSystemLabelField:
    """防再生 ③：HOST_SYSTEM/SYSTEM_ADAPTER 从 adapters/*.yaml 生成
    （system_label 字段=系统名唯一事实源）——新系统零代码接入即有系统名，
    不再两处映射漂移（firefly 8096 曾漏配实证）。"""

    def test_system_maps_from_yaml(self):
        from app.system import HOST_SYSTEM, SYSTEM_ADAPTER
        # 七系统 + firefly 全部来自 yaml system_label（非手工字典）
        assert HOST_SYSTEM.get("127.0.0.1:8069") == "Odoo 销售"
        assert HOST_SYSTEM.get("127.0.0.1:8082") == "禅道项目"
        assert HOST_SYSTEM.get("127.0.0.1:8096") == "Firefly III 记账"
        assert SYSTEM_ADAPTER.get("Odoo 销售") == "odoo"
        assert SYSTEM_ADAPTER.get("Firefly III 记账") == "firefly"

    def test_yaml_system_label_declared(self):
        from app.adapters.manifest import load_adapter_dir
        from pathlib import Path
        ms, _ = load_adapter_dir(Path("adapters"))
        for m in ms:
            assert m.system_label, f"{m.id} 缺 system_label——系统名映射会缺失"

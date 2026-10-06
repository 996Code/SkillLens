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

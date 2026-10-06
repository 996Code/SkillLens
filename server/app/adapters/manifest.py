"""AF1 适配器 manifest：声明式系统接入清单（主计划 v2.1 块 AF）。

三原则：①例程库而非无限 DSL（6 原语，怪癖=routine 按名引用）；
②探针第一公民（docker-exec/http 统一抽象，服务实体验证+状态注入+块 X）；
③flows 可选（缺省=登录引导+人工走查+探针验证）。

安全红线：credentials.password_env 优先；password_literal 仅限本地演示
容器，loader 产出 lint 警告（绝不静默）。
"""
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


PRIMITIVES = ("goto", "fill", "click", "select", "wait", "routine")


class ManifestLint(BaseModel):
    file: str
    code: str
    message: str


class Target(BaseModel):
    base_url: str
    compose: str | None = None


class Credentials(BaseModel):
    username: str = ""
    password_env: str | None = None
    password_literal: str | None = None

    @model_validator(mode="after")
    def _exclusive(self):
        if self.password_env and self.password_literal:
            raise ValueError("password_env 与 password_literal 互斥")
        if not self.password_env and not self.password_literal:
            raise ValueError("凭据须给 password_env（生产）或 password_literal（本地演示）")
        return self


class Step(BaseModel):
    op: str
    arg: str
    arg2: str | None = None

    @model_validator(mode="after")
    def _primitive(self):
        if self.op not in PRIMITIVES:
            raise ValueError(f"未知原语 {self.op}（允许：{PRIMITIVES}）")
        return self


class LoginSuccess(BaseModel):
    """登录成功判定（确定性）：url_not_contains 默认 "login"；
    text_contains 可选补充（如首页特征文本）。"""
    url_not_contains: str = "login"
    text_contains: str | None = None


class Login(BaseModel):
    steps: list[Step]
    post_login: list[str] = []
    success: LoginSuccess = LoginSuccess()


class FlowDef(BaseModel):
    name: str
    steps: list[Step] = []


class HttpRequest(BaseModel):
    method: str = "GET"
    url: str
    json_body: dict | None = Field(default=None, alias="json")

    model_config = {"populate_by_name": True}


class ProbeAssert(BaseModel):
    status: int | None = None
    contains: str | None = None


class Probe(BaseModel):
    id: str
    kind: str = Field(pattern="^(docker-exec|http)$")
    container: str | None = None
    shell: str | None = None
    request: HttpRequest | None = None
    parse_regex: str | None = None
    probe_assert: ProbeAssert | None = Field(default=None, alias="assert")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _kind_shape(self):
        if self.kind == "docker-exec" and not (self.container and self.shell):
            raise ValueError("docker-exec 探针须给 container+shell")
        if self.kind == "http" and self.request is None:
            raise ValueError("http 探针须给 request")
        return self


class ReplayItem(BaseModel):
    skill: str
    overrides: dict[str, str] = {}
    verify_probe: str | None = Field(default=None, alias="verify_probe")
    expect: str | None = Field(default=None, alias="expect")

    model_config = {"populate_by_name": True}


class ChainVerify(BaseModel):
    probe: str
    expect: str


class ReplayWithVerify(BaseModel):
    skill: str
    overrides: dict[str, str] = {}
    verify: ChainVerify | None = None


class Chain(BaseModel):
    name: str
    rounds: int = 2
    skills: list[str]
    replay: list[ReplayWithVerify] = []


class DropdownProfile(BaseModel):
    """下拉菜单交互（ant-dropdown/el-dropdown 家族差异声明）。"""
    engine: str = "generic"                 # ant-design | element-plus | generic
    menu_item_match: str = "exact"          # exact | includes（图标文本混入）
    menu_item_click: str = "trusted"        # trusted（React mousedown 委托）| elclick
    mount_wait_ms: int = 400                # 菜单挂载重试窗口


class ModalSubmitProfile(BaseModel):
    """模态提交按钮（footer 多同名/隐藏副本的选取规则）。"""
    selector: str = ".ant-modal-content, .modal-content, [role=dialog]"
    button_regex: str = "保存|确定|提\\s*交"
    pick: str = "last_visible"              # last_visible | first_visible
    render_wait_ms: int = 800


class FormFillProfile(BaseModel):
    """表单填充定位器序与框架通道。"""
    framework: str = "generic"              # generic | frappe
    field_locators: list[str] = Field(default_factory=lambda: [
        "data-fieldname", "placeholder", "form-item-label", "name-attr"])
    same_label_priority: str = "modal_first"  # modal_first | first


class RowActionProfile(BaseModel):
    """表格行操作（行锚/滚入）。"""
    anchor_match: str = "sensitive"          # insensitive（存储层 lowercase）
    scroll_into_view: bool = True


class RouteGuardProfile(BaseModel):
    """SPA 路由守卫（异步 set_route 跳变防护+实例 URL 归一）。"""
    async_set_route: bool = False
    normalize_new_suffix: bool = False       # /new-xxx 随机后缀剥离


class InteractionProfile(BaseModel):
    """交互画像（P1 平台化组件化）：执行器特化分支的声明式载体——
    新系统接入改 YAML 不改执行器源码。"""
    dropdown: DropdownProfile | None = None
    modal_submit: ModalSubmitProfile | None = None
    form_fill: FormFillProfile | None = None
    row_action: RowActionProfile | None = None
    route_guard: RouteGuardProfile | None = None


class Manifest(BaseModel):
    id: str
    label: str = ""
    target: Target
    credentials: Credentials
    login: Login | None = None
    flows: list[FlowDef] | None = None
    probes: list[Probe] = []
    chains: list[Chain] = []
    interaction_profile: InteractionProfile | None = None
    # P2.5 URL 通配符匹配（油猴 @match 语义）：声明此清单接管哪些 URL——
    # goto/采集 URL 命中即自动配对该系统的画像/链路/组件（自动隔离）；
    # specificity=去通配符长度（具体规则胜过通配）
    url_matches: list[str] = Field(default_factory=list)


def _steps_from_raw(raw: list) -> list[Step]:
    """YAML 微形态 → Step：- goto: /x  |  - fill: ["sel", "val"]  |  - routine: name"""
    out = []
    for item in raw or []:
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError(f"步骤须单键 dict：{item}")
        op, arg = next(iter(item.items()))
        if op == "fill" or op == "select":
            if not (isinstance(arg, list) and len(arg) == 2):
                raise ValueError(f"{op} 原语参数须 [selector, value]")
            out.append(Step(op=op, arg=arg[0], arg2=arg[1]))
        elif op == "wait":
            out.append(Step(op="wait", arg=str(arg)))
        else:
            out.append(Step(op=op, arg=str(arg)))
    return out


def _parse(doc: dict) -> Manifest:
    if doc.get("login"):
        doc["login"] = {
            "steps": [s.model_dump() for s in _steps_from_raw(doc["login"].get("steps"))],
            "post_login": doc["login"].get("post_login") or [],
            "success": doc["login"].get("success") or {},
        }
    for f in doc.get("flows") or []:
        f["steps"] = [s.model_dump() for s in _steps_from_raw(f.get("steps"))]
    return Manifest(**doc)


def load_manifest_text(text: str, filename: str = "<text>") -> tuple[Manifest, list[ManifestLint]]:
    m = _parse(yaml.safe_load(text))
    lints: list[ManifestLint] = []
    if m.credentials.password_literal:
        lints.append(ManifestLint(
            file=filename, code="password_literal",
            message="password_literal 仅限本地演示容器；生产接入改用 password_env（安全红线）"))
    return m, lints


def load_adapter_dir(directory: Path) -> tuple[list[Manifest], list[ManifestLint]]:
    manifests: list[Manifest] = []
    lints: list[ManifestLint] = []
    for f in sorted(Path(directory).glob("*.yaml")):
        m, ls = load_manifest_text(f.read_text(encoding="utf-8"), f.name)
        manifests.append(m)
        lints.extend(ls)
    return manifests, lints

"""AF1 适配器 manifest：声明式系统接入清单（主计划 v2.1 块 AF）。

三原则：①例程库而非无限 DSL（6 原语，怪癖=routine 按名引用）；
②探针第一公民（docker-exec/http 统一抽象，服务实体验证+状态注入+块 X）；
③flows 可选（缺省=登录引导+人工走查+探针验证）。

安全红线：credentials.password_env 优先；password_literal 仅限本地演示
容器，loader 产出 lint 警告（绝不静默）。清单文本出网（API 回显）前
必须过 redact_manifest_text 脱敏。
"""
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


PRIMITIVES = ("goto", "fill", "click", "select", "wait", "routine")

# 评审三轮 #2：container 直入 docker argv——`-`/`.` 开头会被 docker 解析为
# 选项（--user=0 → root 进容器），清单 reviewer 可写盘 → schema 层封死
_CONTAINER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


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
    # 评审三轮 #4：steps.login 身份校验读此字段——缺声明时曾静默丢弃
    # （extra=ignore）致校验分支死代码；期望昵称不符 → 强制退出重登
    admin_nickname: str | None = None


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
    container: str | None = Field(default=None, pattern=_CONTAINER_PATTERN)
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
    engine: str = "generic"                 # ant-design | element-plus | generic | select2
    menu_item_match: str = "exact"          # exact | includes（图标文本混入）
    menu_item_click: str = "trusted"        # trusted（React mousedown 委托）| elclick
    mount_wait_ms: int = 400                # 菜单挂载重试窗口
    # AO1（引擎零系统知识）：菜单项选择器外置——默认=原插件硬编码值
    menu_item_selector: str = (
        ".ant-dropdown-menu-item, .el-dropdown-menu__item")
    # hover 流入场景的宽兜底链（dropdown 匹配失败后的最后防线）
    menu_item_selector_fallback: str = (
        ".el-dropdown-menu__item, .ant-dropdown-menu-item, "
        "li [role=menuitem], li")


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
    # AO1（引擎零系统知识）：表单容器/自绘控件/校验错误选择器外置——
    # 默认=原引擎硬编码值（向后兼容锚，test_adapter_manifest 锁定）
    container_selector: str = (
        ".form-group, .ant-form-item, [class*=form-group]")
    control_selector: str = (
        ".select2-container, .picker, .ant-select, .ant-picker")
    validation_error_selector: str = (
        ".ant-form-item-explain-error, .el-form-item__error, "
        ".invalid-feedback, .form-control-feedback")


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
    # 系统名（HOST_SYSTEM/SYSTEM_ADAPTER 的生成源——防再生③：映射单一
    # 事实源；label 是展示名（含版本号），system_label 是稳定系统名）
    system_label: str = ""
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
            "admin_nickname": doc["login"].get("admin_nickname"),
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
    # 评审三轮 #5b：匹配引擎按油猴语义剥离 query——含 `?` 的模式永不命中，
    # 显式警示作者（静默失效曾无从排查）
    for pat in m.url_matches:
        if "?" in pat:
            lints.append(ManifestLint(
                file=filename, code="url_match_query",
                message=f"url_matches 模式含查询串（{pat}）——@match 语义不比对"
                        " query，此模式永不命中；请去掉 ? 及其后内容"))
    return m, lints


# 评审三轮 #1：敏感键名（值即秘密）——出网文本统一掩码；*_env 存的是环境
# 变量名（引用非值），保留以维持排障能力
_SENSITIVE_KEY_RE = re.compile(r"password|secret|token|api_?key|credential", re.I)


def _is_secret_key(key) -> bool:
    return (isinstance(key, str) and not key.endswith("_env")
            and bool(_SENSITIVE_KEY_RE.search(key)))


def _redact_obj(o):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            # 敏感键持容器（如 credentials 块）→ 递归逐键裁决——块内
            # password_env（变量名引用）/username 非秘密值，不得整块掩掉
            if _is_secret_key(k) and not isinstance(v, (dict, list)):
                out[k] = "***"
            else:
                out[k] = _redact_obj(v)
        return out
    if isinstance(o, list):
        return [_redact_obj(v) for v in o]
    return o


_LINE_MASK_RE = re.compile(
    r"^(?P<head>\s*(?:-\s+)?)(?P<key>[A-Za-z0-9_.\-]+)(?P<sep>\s*:\s)(?P<val>\S.*)$",
    re.M)


def redact_manifest_text(text: str) -> str:
    """清单文本脱敏（GET /adapters/{id}/yaml 回显前必过）：敏感键值 →
    "***"，其余结构原样重序列化。解析失败降级行级正则掩码——任何路径
    都绝不原文返回秘密值。"""
    try:
        doc = yaml.safe_load(text)
        if isinstance(doc, (dict, list)):
            return yaml.safe_dump(_redact_obj(doc), allow_unicode=True,
                                  sort_keys=False)
    except Exception:
        pass

    def _sub(m):
        if _is_secret_key(m.group("key")):
            return f'{m.group("head")}{m.group("key")}{m.group("sep")}"***"'
        return m.group(0)

    return _LINE_MASK_RE.sub(_sub, text)


# 掩码值（redact_manifest_text 写入的哨兵）——保存时据此判定"用户没改这个键"
MASK_VALUE = "***"

# 仍是掩码的敏感键（块式与内联 flow 两种形态都覆盖）
_MASKED_SECRET_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_.\-]+)(?P<sep>\s*:\s*)(?P<q>[\"'])?"
    + re.escape(MASK_VALUE) + r"(?P=q)")
# 磁盘旧文本里的敏感键值（带原引号形态，回填后 YAML 语义不变）
_SECRET_VALUE_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_.\-]+)(?P<sep>\s*:\s*)"
    r"(?P<val>\"[^\"]*\"|'[^']*'|[^\s,}\]]+)")


def restore_masked_secrets(new_text: str, old_text: str | None) -> str:
    """脱敏回显的逆操作：保存时把仍是掩码的敏感键回填磁盘旧值。

    GET /adapters/{id}/yaml 返回脱敏文本（安全红线），工作台编辑器原样
    PUT 就会把 `***` 写进清单——改个 label 顺手销毁演示容器口令，登录
    静默失败且无从排查。只回填仍是掩码的键：用户显式改写过的值以新值为准。
    行级替换而非重序列化，保留用户注释；同名键多次出现按出现序配对。
    """
    if not old_text:
        return new_text
    from collections import defaultdict, deque
    old: dict[str, deque] = defaultdict(deque)
    for m in _SECRET_VALUE_RE.finditer(old_text):
        if _is_secret_key(m.group("key")):
            old[m.group("key")].append(m.group("val"))

    def _sub(m):
        key = m.group("key")
        pending = old.get(key)
        if not _is_secret_key(key) or not pending:
            return m.group(0)      # 非敏感键/无旧值可回填：保持掩码原样
        return f'{key}{m.group("sep")}{pending.popleft()}'

    return _MASKED_SECRET_RE.sub(_sub, new_text)


def load_adapter_dir(directory: Path) -> tuple[list[Manifest], list[ManifestLint]]:
    """目录扫描：单份坏 YAML 降级为 parse_error lint 条目并跳过——
    健康清单照常返回（评审三轮 #6：一份坏文件曾令 /adapters 全线 500）。"""
    manifests: list[Manifest] = []
    lints: list[ManifestLint] = []
    for f in sorted(Path(directory).glob("*.yaml")):
        try:
            m, ls = load_manifest_text(f.read_text(encoding="utf-8"), f.name)
        except Exception as e:
            lints.append(ManifestLint(
                file=f.name, code="parse_error",
                message=f"清单解析/校验失败，已跳过: {str(e)[:200]}"))
            continue
        manifests.append(m)
        lints.extend(ls)
    return manifests, lints

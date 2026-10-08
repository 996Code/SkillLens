"""AJ1 失败分类学：run 级分类器纯函数（规则表驱动，判定全确定性——宪法 C1）。

分类（业界互证：TestRail Fail/Blocked/Retest + quarantine 流水线 + zcode 错误三码）：
- e1_env      环境故障：登录态丢失（证据 URL 落 login 路径）/目标站不可达/导航超时
- e2_infra    基础设施故障：LLM 网关额度/断连（我们自己的错）
- e3_drift    链路漂移：定位 miss（URL 在业务页）/断言失败——需要自愈/重录
- e4_expected 预期内失败（负向用例/C1 拦截）——当前无判定入口，占位
- None        pass/shadow/无证据（不猜）

口径纪律（TestRail）：E1/E2 不进通过率分母；blocked（没跑）≠ fail。
派生值（flaky_verdict 等）不落库——查询时聚合，口径变更可重算。
"""
import re

# 登录态特征：URL 出现 login 路径（适配器 url_not_contains 的通用反查）；
# 禅道实证补强：query 风格登录（?m=user&f=login）非路径风格——词表须覆盖
_LOGIN_URL_RE = re.compile(
    r"/login\b|/login\?|login\.php|/signin|[?&][a-z_]+=login\b", re.IGNORECASE)
# 业务页但非 login 的判定：排除法（守卫只看证据 URL）
_CHROME_ERROR_RE = re.compile(r"chrome-error://|ERR_CONNECTION|ERR_NAME|net::ERR", re.IGNORECASE)
_NAV_TIMEOUT_RE = re.compile(r"Timeout \d+ms exceeded.*(goto|navigat)|page\.goto.*Timeout", re.IGNORECASE)
_INFRA_RE = re.compile(r"Token额度|token 额度|额度不足|llm.?gateway|ECONNREFUSED.*8710", re.IGNORECASE)


def _step_urls(executed: list) -> list[str]:
    urls = []
    for st in executed or []:
        err = str(st.get("error") or "")
        urls.append(err)
        # scene/URL 直接在 error 文本里（"@ url"）——已含于 err
    return urls


def classify_run(run: dict) -> str | None:
    """run dict（executed/assertions/status）→ failure_class。

    优先级：e2（我们错）> e1（环境）> e3（漂移）——先排除基础设施自身
    故障再归环境，避免把网关额度误判成"目标站宕机"。
    """
    status = run.get("status")
    if status in ("pass", "shadow"):
        return None
    executed = run.get("executed") or []
    errs = _step_urls(executed)
    err_all = " ".join(errs)

    if _INFRA_RE.search(err_all):
        return "e2_infra"
    for e in errs:
        if _LOGIN_URL_RE.search(e):
            return "e1_env"
    if _CHROME_ERROR_RE.search(err_all) or _NAV_TIMEOUT_RE.search(err_all):
        return "e1_env"
    # 有失败步骤且 URL 在业务页（定位 miss）或有断言失败
    if any((st.get("ok") is False and st.get("kind") != "goto") for st in executed):
        return "e3_drift"
    for a in run.get("assertions") or []:
        if a.get("passed") is False and not a.get("skipped"):
            return "e3_drift"
    return None  # 无证据不猜（如 fail 但零步骤——保守 null）


def pass_rate(runs: list[dict]) -> dict:
    """通过率口径：E1/E2/blocked 不进分母（业界共识，arch 文档版本化）。"""
    counted = [r for r in runs
               if r.get("failure_class") not in ("e1_env", "e2_infra")
               and r.get("status") not in ("blocked",)]
    npass = sum(1 for r in counted if r.get("status") == "pass")
    total = len(counted)
    return {"pass": npass, "total": total,
            "rate": round(npass / total, 4) if total else None}


# AJ2 守卫触发谓词（Dolibarr 实证补强）：登录页现场两种证据形态——
# URL 落 login 路径（SPA 系统），或页面标题是登录页（经典表单系统
# 会话过期后 URL 停在业务路径、标题变 "Login"，错误串里无 login 字样）
_LOGIN_TITLE_RE = re.compile(
    r"^\s*(login|log\s*in|sign\s*in|signin|登录|登陆|用户登录)"
    r"\s*(?:[|·\-—@:：].*)?$",
    re.IGNORECASE)


def login_page_evidence(error_text: str, page_title: str | None) -> bool:
    """错误串/页面标题是否指向登录页现场（AJ2 守卫与分类共用）。"""
    if _LOGIN_URL_RE.search(error_text or ""):
        return True
    if page_title and _LOGIN_TITLE_RE.match(page_title):
        return True
    return False

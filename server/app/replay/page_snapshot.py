"""回放侧 UI 状态快照（Sprint 8 块B T4）。

schema 与插件 Snapshot（extension/src/content/snapshot.ts + shared/types.ts）对齐：
{phase, ts, forms: [{label, value}], labels: [{text}], tables: [{label, rows}], overflow?}
红线同步：≤50 字段、单值 ≤1024 字符、labels ≤20、tables ≤10、密码框整体跳过、
敏感 label 脱敏（与插件 shared/redact.ts 同词表）。
label 语义与 describe-element 同源：aria-label → placeholder → title → 累积文本
（兜底文本截 100，与 extension/src/shared/describe-element.ts slice(0,100) 对齐）。
"""
import re
import time

from playwright.async_api import Page

from app import config

MAX_FIELDS = 50
MAX_VALUE_CHARS = 1024
MAX_LABELS = 20
MAX_LABEL_CHARS = 100
MAX_TABLES = 10
REDACTED = "[REDACTED]"

# 与 extension/src/shared/redact.ts 的 BASE_SENSITIVE_PATTERNS 逐字同表
# （一致性由 extension/src/shared/redact-parity.test.ts 跨文件断言）；
# J4：config.PII_PATTERNS（env 逗号分隔）追加私有化部署自定义敏感字段
_BASE_SENSITIVE_PATTERNS = [
    "password", "passwd", "secret", "token", "authorization", "cookie",
    "api_key", "apikey", "private_key", "credential",
    "密码", "口令", "密钥", "令牌", "凭证", "验证码",
]


def _rebuild_sensitive_re():
    """基础词表 + config.PII_PATTERNS 合并构造敏感正则。

    模块级构造一次；测试/配置刷新时重新调用（配合 importlib.reload(config)）。
    """
    global SENSITIVE_KEY_RE
    parts = _BASE_SENSITIVE_PATTERNS + list(config.PII_PATTERNS)
    SENSITIVE_KEY_RE = re.compile("|".join(parts), re.I)
    return SENSITIVE_KEY_RE


SENSITIVE_KEY_RE = _rebuild_sensitive_re()

_FIELD_SELECTOR = "input, select, textarea"
_LABEL_SELECTOR = '[class*="tag"], [class*="status"], [class*="badge"]'


def redact_value(key: str, value: str) -> str:
    return REDACTED if SENSITIVE_KEY_RE.search(key) else value


async def _field_label(el) -> str:
    """label 兜底链与 describe-element 同源：aria-label → placeholder → title → 累积文本。
    元素 detach（React 重渲染换节点）时返回 ""，不抛异常。"""
    for attr in ("aria-label", "placeholder", "title"):
        try:
            v = await el.get_attribute(attr)
        except Exception:
            return ""  # 元素已 detach
        if v:
            return v
    try:
        text = (await el.text_content() or "").strip()
    except Exception:
        text = ""
    return text[:MAX_LABEL_CHARS]


def _iter_frames(page):
    """评审#6：iframe 架构应用（禅道综合页面等）业务内容渲染在子 frame——
    与 locate._try_locate 同走 frame 遍历（主 frame 优先），否则 forms/
    labels/toasts 全空：ui_text 断言静默跳过、toast 通道失效、修复提案池为空。
    主 frame 的采集必须经传入 page 对象本身（测试替身/代理以
    query_selector_all 拦截模拟 detach 等场景）；无 frames 属性的替身
    回退单 page。"""
    frames = getattr(page, "frames", None)
    if not frames:
        return [page]
    main = getattr(page, "main_frame", None)
    return [page] + [f for f in frames if f is not main]


async def collect_page_snapshot(page: Page, phase: str = "after") -> dict:
    """采集当前页面的轻量 UI 状态（遍历全部 frame 聚合；红线限额是
    **全局总量**非逐 frame）。forms 为断言必需；labels/tables 保持结构对齐。"""
    forms: list[dict] = []
    overflow = False
    for fr in _iter_frames(page):
        if overflow:
            break
        try:
            fields = await fr.query_selector_all(_FIELD_SELECTOR)
        except Exception:
            continue  # frame 已销毁（导航竞态）→ 跳过该 frame
        for el in fields:
            if overflow:
                break
            try:
                input_type = (await el.get_attribute("type") or "").lower()
            except Exception:
                continue
            if input_type == "password":
                continue  # 密码框整体跳过（连 label 都不落）
            if len(forms) >= MAX_FIELDS:
                overflow = True
                break
            label = await _field_label(el)
            try:
                value = (await el.input_value() or "")[:MAX_VALUE_CHARS]
            except Exception:
                value = ""
            forms.append({"label": label, "value": redact_value(label, str(value))})

    snap = {"phase": phase, "ts": int(time.time() * 1000),
            "forms": forms,
            "labels": await _collect_labels(page),
            "tables": await _collect_tables(page)}
    toasts = await _collect_toasts(page)
    if toasts:
        snap["toasts"] = toasts
    if overflow:
        snap["overflow"] = True
    return snap


async def _collect_toasts(page: Page) -> list[str]:
    """层1 显式提示：可见 toast/消息文本（≤3 条×100 字符，敏感词整条丢弃）。
    与插件 collectToasts 同规则；可见性近似（fixed 定位 offsetParent 为 null）。
    全部 frame 聚合，3 条为全局上限。"""
    out: list[str] = []
    for fr in _iter_frames(page):
        if len(out) >= 3:
            break
        try:
            els = await fr.query_selector_all(".n-message, [class*=message]")
        except Exception:
            continue
        for el in els:
            if len(out) >= 3:
                break
            try:
                hidden = await el.get_attribute("hidden")
                aria = await el.get_attribute("aria-hidden")
                if hidden is not None or aria == "true":
                    continue
                text = ((await el.inner_text() or "").strip())[:100]
            except Exception:
                continue  # detach 容错
            if text and not SENSITIVE_KEY_RE.search(text):
                out.append(text)
    return out


async def _collect_labels(page: Page) -> list[dict]:
    out: list[dict] = []
    for fr in _iter_frames(page):
        if len(out) >= MAX_LABELS:
            break
        try:
            els = await fr.query_selector_all(_LABEL_SELECTOR)
        except Exception:
            continue
        for el in els:
            if len(out) >= MAX_LABELS:
                break
            try:
                # 可见过滤近似（与插件 CS 侧 closest(':not([aria-hidden="true"])') 对齐的
                # server 侧实现）：display:none / visibility:hidden / hidden 属性 /
                # 任一祖先 aria-hidden=true 视为不可见。用一次 evaluate 查祖先链。
                visible = await el.evaluate(
                    "el => {for (let n = el; n; n = n.parentElement) {"
                    "  if (n.hidden) return false;"
                    "  const s = getComputedStyle(n);"
                    "  if (s.display === 'none' || s.visibility === 'hidden') return false;"
                    "  if (n.getAttribute && n.getAttribute('aria-hidden') === 'true') return false;"
                    "} return true;}")
                if not visible:
                    continue
                text = ((await el.text_content() or "").strip())[:MAX_LABEL_CHARS]
            except Exception:
                continue  # 元素 detach → 跳过该条
            if text:
                out.append({"text": text})
    return out


async def _collect_tables(page: Page) -> list[dict]:
    out: list[dict] = []
    for fr in _iter_frames(page):
        if len(out) >= MAX_TABLES:
            break
        try:
            tables = await fr.query_selector_all("table")
        except Exception:
            continue
        for tb in tables:
            if len(out) >= MAX_TABLES:
                break
            try:
                rows = await tb.evaluate(
                    "el => {const tb=el.querySelectorAll('tbody');"
                    "if (tb.length) return Array.from(tb).reduce((n,t)=>n+t.querySelectorAll('tr').length,0);"
                    "return Math.max(el.querySelectorAll('tr').length-1,0);}")
                label = await tb.get_attribute("aria-label") or ""
                if not label:
                    label = await tb.evaluate(
                        "el => {const c=el.querySelector('caption');"
                        "if (c && c.textContent.trim()) return c.textContent.trim();"
                        "let cur=el.previousElementSibling;"
                        "while (cur) {if (/^h[1-6]$/i.test(cur.tagName) && cur.textContent.trim())"
                        "return cur.textContent.trim(); cur=cur.previousElementSibling;}"
                        "return '';}")
            except Exception:
                continue  # frame/元素 detach 容错
            out.append({"label": (label or "")[:MAX_LABEL_CHARS], "rows": rows})
    return out

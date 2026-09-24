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

MAX_FIELDS = 50
MAX_VALUE_CHARS = 1024
MAX_LABELS = 20
MAX_LABEL_CHARS = 100
MAX_TABLES = 10
REDACTED = "[REDACTED]"

# 与 extension/src/shared/redact.ts 的 SENSITIVE_KEY_RE 同词表
SENSITIVE_KEY_RE = re.compile(r"password|passwd|secret|token|authorization|cookie", re.I)

_FIELD_SELECTOR = "input, select, textarea"
_LABEL_SELECTOR = '[class*="tag"], [class*="status"], [class*="badge"]'


def redact_value(key: str, value: str) -> str:
    return REDACTED if SENSITIVE_KEY_RE.search(key) else value


async def _field_label(page: Page, el) -> str:
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


async def collect_page_snapshot(page: Page, phase: str = "after") -> dict:
    """采集当前页面的轻量 UI 状态。forms 为断言必需；labels/tables 保持结构对齐。"""
    forms: list[dict] = []
    overflow = False
    fields = await page.query_selector_all(_FIELD_SELECTOR)
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
        label = await _field_label(page, el)
        try:
            value = (await el.input_value() or "")[:MAX_VALUE_CHARS]
        except Exception:
            value = ""
        forms.append({"label": label, "value": redact_value(label, str(value))})

    snap = {"phase": phase, "ts": int(time.time() * 1000),
            "forms": forms,
            "labels": await _collect_labels(page),
            "tables": await _collect_tables(page)}
    if overflow:
        snap["overflow"] = True
    return snap


async def _collect_labels(page: Page) -> list[dict]:
    out: list[dict] = []
    els = await page.query_selector_all(_LABEL_SELECTOR)
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
    tables = await page.query_selector_all("table")
    for tb in tables:
        if len(out) >= MAX_TABLES:
            break
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
        out.append({"label": (label or "")[:MAX_LABEL_CHARS], "rows": rows})
    return out

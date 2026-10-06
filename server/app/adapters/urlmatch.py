"""P2.5 URL 通配符匹配引擎（油猴 @match 语义）。

规则：模式 `http://host[:port]/path*`；`*` 通配任意字符；specificity =
模式去通配符后的长度（具体规则胜过通配——油猴同语义）。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """`http://127.0.0.1:8095/*` → 全匹配正则（* → .*，其余转义）。"""
    escaped = re.escape(pattern)
    return re.compile("^" + escaped.replace(r"\*", ".*") + "$")


def url_pattern_match(url: str, pattern: str) -> bool:
    """单模式匹配（query 忽略——对齐油猴 @match 语义）。"""
    url_path = urlsplit(url)
    target = f"{url_path.scheme}://{url_path.netloc}{url_path.path}"
    # 模式无路径尾（如 http://host）——补 / 匹配站点根
    if not urlsplit(pattern).path and target.endswith("/"):
        target = target.rstrip("/")
    return bool(_pattern_to_regex(pattern).match(target))


def match_adapter(url: str, manifests: list) -> object | None:
    """URL → 命中的 manifest（specificity 最长优先；无声明不参与）。"""
    best = None
    best_spec = -1
    for m in manifests:
        for pat in getattr(m, "url_matches", []) or []:
            if url_pattern_match(url, pat):
                spec = len(pat.replace("*", ""))
                if spec > best_spec:
                    best_spec = spec
                    best = m
    return best

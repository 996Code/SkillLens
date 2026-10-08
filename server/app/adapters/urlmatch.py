"""P2.5 URL 通配符匹配引擎（油猴 @match 语义）。

规则：模式 `http://host[:port]/path*`；specificity = 模式去通配符后的长度
（具体规则胜过通配——油猴同语义）。

通配符边界（评审三轮 #5a）：host 段 `*` 编译为 `[^./]*`——至多匹配一个
label，不跨 `.`/`/`（`.*` 曾让 `http://evil.com/.example.com/x` 伪装命中
`http://*.example.com/*`）；路径段 `*` 保持 `.*`（跨 `/`，油猴同语义）。

query（评审三轮 #5b）：比对前剥离 URL 的查询串——含 `?` 的模式永不命中，
loader 侧产 url_match_query lint 警示作者（manifest.load_manifest_text）。

tie-break（评审三轮 #5c）：同 specificity 按 (specificity 降序, manifest id
升序) 确定性收敛——不再依赖清单迭代序（文件名序）。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_SCHEME_RE = re.compile(r"^(?P<scheme>[A-Za-z0-9+.\-]+://)?(?P<rest>.*)$")


def _compile_segment(seg: str, *, host: bool) -> str:
    """段内 `*` → 正则：host 段单 label（[^./]*），路径段任意（.*）。"""
    return re.escape(seg).replace(r"\*", "[^./]*" if host else ".*")


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """`http://*.example.com/app/*` → 全匹配正则（authority 与 path 分治）。"""
    m = _SCHEME_RE.match(pattern)
    scheme, rest = m.group("scheme") or "", m.group("rest")
    slash = rest.find("/")
    authority, path = (rest, "") if slash < 0 else (rest[:slash], rest[slash:])
    return re.compile("^" + re.escape(scheme)
                      + _compile_segment(authority, host=True)
                      + _compile_segment(path, host=False) + "$")


def url_pattern_match(url: str, pattern: str) -> bool:
    """单模式匹配（query 忽略——对齐油猴 @match 语义，见模块 docstring）。"""
    url_path = urlsplit(url)
    target = f"{url_path.scheme}://{url_path.netloc}{url_path.path}"
    # 模式无路径尾（如 http://host）——补 / 匹配站点根
    if not urlsplit(pattern).path and target.endswith("/"):
        target = target.rstrip("/")
    return bool(_pattern_to_regex(pattern).match(target))


def match_adapter(url: str, manifests: list) -> object | None:
    """URL → 命中的 manifest：specificity（去 `*` 长度）降序，同分按
    manifest id 升序确定性 tie-break（见模块 docstring）；无声明不参与。"""
    best = None
    best_key: tuple[int, str] | None = None
    for m in manifests:
        for pat in getattr(m, "url_matches", []) or []:
            if url_pattern_match(url, pat):
                key = (-len(pat.replace("*", "")), str(getattr(m, "id", "")))
                if best_key is None or key < best_key:
                    best_key = key
                    best = m
    return best

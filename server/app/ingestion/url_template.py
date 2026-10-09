import re
from urllib.parse import urlsplit

NUMERIC = re.compile(r"^\d+$")
UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# S43-4：32 位无连字符 hex（JeecG online 表 code 等——跨会话实体标识，
# 不模板化则断言 URL 精确匹配录制实体必失配）
HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def split_url(url: str) -> tuple[str, str]:
    if url.startswith("http://") or url.startswith("https://"):
        parts = urlsplit(url)
        return parts.path or "/", parts.query or ""
    path, _, query = url.partition("?")
    return path or "/", query


def templatize_path(path: str) -> tuple[str, list[dict]]:
    segments = path.split("/")
    template_parts: list[str] = []
    params: list[dict] = []
    for seg in segments:
        if NUMERIC.match(seg) or UUID.match(seg) or HEX32.match(seg):
            template_parts.append("{id}")
            params.append({"name": f"id_{len(params)}", "value": seg})
        else:
            template_parts.append(seg)
    return "/".join(template_parts), params


# P2-10 query 模板化（禅道单入口实证：路由语义在 m/f 参数里，模板丢
# query 就无区分度——93/95 断言都落 /index.php）：
# - 只保留路由语义参数：短字母值（≤24、字母数字与-_）、非动态形态
#   （纯数字/UUID/长 hex=实体 id，跨轮漂移）、非敏感名（token/key/密码类）
# - 动态值与敏感参数剔除（不进模板）；无可用参数则不带 query（旧形态）
_SENSITIVE_PARAM = re.compile(r"token|key|secret|password|passwd|signature|sign|密码|令牌",
                              re.IGNORECASE)
# 分页/排序/会话态/回跳参数：值随上下文变（非路由标识）——剔除
_VOLATILE_PARAM = re.compile(r"^(?:order|sort|orderby|page|pagesize|limit|offset|"
                             r"recTotal|perPage|currentPage|lang|theme|t|_|"
                             r"referer|back|redirect|return|callback|url)$",
                             re.IGNORECASE)
_DYNAMIC_VALUE = re.compile(r"^(?:\d+|[0-9a-fA-F-]{36}|[0-9a-fA-F]{16,}|%[0-9A-Fa-f]{2}.*)$")
_ROUTING_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,23}$")


def templatize_query(query: str) -> str:
    """路由语义参数进模板（m=story&f=create 形态）；动态/敏感/分页排序/
    非语义值剔除。"""
    from urllib.parse import parse_qsl
    keep: list[tuple[str, str]] = []
    for k, v in parse_qsl(query):
        if not k or not v:
            continue
        if _SENSITIVE_PARAM.search(k) or _VOLATILE_PARAM.match(k):
            continue
        if _DYNAMIC_VALUE.match(v):
            continue
        if not _ROUTING_VALUE.match(v):
            continue
        keep.append((k, v))
    if not keep:
        return ""
    return "&".join(f"{k}={v}" for k, v in keep)

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

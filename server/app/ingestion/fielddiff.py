import hashlib


TRUNCATE_LIMIT_BYTES = 8192


def flatten(obj: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def diff_bodies(before: dict, after: dict) -> list[dict]:
    fb, fa = flatten(before), flatten(after)
    fields = sorted(set(fb) | set(fa))
    return [{"field": f, "before": fb.get(f), "after": fa.get(f)}
            for f in fields if fb.get(f) != fa.get(f)]


def truncate_req_body(raw: str) -> dict:
    """reqBody 超 TRUNCATE_LIMIT_BYTES 字节时的入库保护：
    返回全文 sha256（hex 64）与截断文本；8KB 内 truncated=False 原样返回。"""
    data = raw.encode("utf-8")
    if len(data) <= TRUNCATE_LIMIT_BYTES:
        return {"text": raw, "truncated": False, "sha256": None}
    return {"text": data[:TRUNCATE_LIMIT_BYTES].decode("utf-8", errors="ignore"),
            "truncated": True,
            "sha256": hashlib.sha256(data).hexdigest()}


def cap_value(v) -> object:
    """changes 落库值的全文不入库保护：超限字符串截断存前缀。"""
    if isinstance(v, str) and len(v.encode("utf-8")) > TRUNCATE_LIMIT_BYTES:
        return v.encode("utf-8")[:TRUNCATE_LIMIT_BYTES].decode("utf-8", errors="ignore") + "…[truncated]"
    return v

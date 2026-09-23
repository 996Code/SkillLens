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

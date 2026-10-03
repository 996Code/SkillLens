"""AF5 链编排器：清单 chains 驱动 record→learn→replay→verify 全自动。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/af5_chain.py jeecg

链语义（chains[].replay）：
- overrides 的 ${ts} 每链一轮注入（换参）；
- replay 走服务端 replay API（executor 端在 AG5 接入双端）；
- verify 探针 expect: increased/equals（AF2 运行时）。
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app.adapters.manifest import load_adapter_dir, Manifest, Chain
from app.adapters.probes import run_probe, compare_expect, interpolate

SERVER = "http://127.0.0.1:8710/api/v1"


def mint_token() -> str:
    from app.auth import issue_token
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin").first()
        return issue_token(db, u.id)
    finally:
        db.close()


def resolve_skill_id(token: str, name: str) -> int | None:
    """技能引用 → id：数字串直引（LLM 命名不稳定），否则按名最新非 superseded。"""
    if name.isdigit():
        return int(name)
    with httpx.Client(timeout=30) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        r = c.get(f"{SERVER}/executor/skills")
        for s in r.json():
            if s["name"] == name:
                return s["id"]
    return None


async def replay_and_verify(token: str, manifest: Manifest, chain: Chain,
                            ts: int) -> dict:
    results = {}
    probes = {p.id: p for p in manifest.probes}
    async with httpx.AsyncClient(timeout=600) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for item in chain.replay:
            sid = resolve_skill_id(token, item.skill)
            if not sid:
                results[item.skill] = "skill-not-found"
                continue
            overrides = {k: interpolate(v.replace("${ts}", str(ts)), manifest)
                         for k, v in item.overrides.items()}
            verify_before = None
            if item.verify and item.verify.probe in probes:
                verify_before = run_probe(manifest, probes[item.verify.probe])
            r = await c.post(f"{SERVER}/skills/{sid}/replay",
                             json={"overrides": overrides,
                                   "confirm_side_effect": True})
            body = r.json() if r.status_code == 200 else {"status": f"http{r.status_code}"}
            verdict = body.get("status")
            if item.verify and item.verify.probe in probes:
                after = run_probe(manifest, probes[item.verify.probe])
                ok = compare_expect(item.verify.expect, verify_before, after)
                verdict = f"{verdict}+{'verified' if ok else 'VERIFY_FAIL'}"
            results[item.skill] = verdict
    return results


async def ensure_login(manifest: Manifest) -> bool:
    """回放前登录（9222 常驻浏览器，AF3 login 幂等——已登录直通）。"""
    from playwright.async_api import async_playwright
    from app.adapters.steps import login as adapter_login
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = b.contexts[0].pages[0]
        return await adapter_login(page, manifest)


async def main():
    adapter_id = sys.argv[1] if len(sys.argv) > 1 else "jeecg"
    chain_name = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"=== AF5 链编排：{adapter_id} ===")
    manifests, _ = load_adapter_dir(Path(__file__).resolve().parent.parent / "adapters")
    m = {x.id: x for x in manifests}[adapter_id]
    token = mint_token()
    ts = int(time.time()) % 100000
    if not await ensure_login(m):
        print("! 登录失败——中止")
        return
    print("登录 OK（幂等）")
    for chain in m.chains:
        if chain_name and chain.name != chain_name:
            continue
        print(f"\n[{chain.name}] replay+verify：")
        res = await replay_and_verify(token, m, chain, ts)
        for k, v in res.items():
            print(f"  {k}: {v}")
        ok = all("fail" not in str(v).lower() and "not-found" not in str(v) for v in res.values())
        print(f"  链结论: {'ALL PASS' if ok and res else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())

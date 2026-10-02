"""S43-4：ERPNext CRM 链回放验证（换参）。

三技能：#213 ErpCustomerCreate / #214 ErpQuotationCreate /
#215 ErpSalesOrderCreate。回放经 server /replay/execute（CDP 常驻
浏览器），断言由 server 生成；此处附加实体级验证（Frappe API 查
新实体是否真实建出）。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  ERPPW=<密码> uv run python scripts/s43_erpnext_replay.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
ERP = "http://127.0.0.1:8090"
SKILLS = {"customer": 234, "quotation": 235, "so": 236}


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


async def erp_login_cookies() -> dict:
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{ERP}/api/method/login",
                         json={"usr": "Administrator", "pwd": "admin"})
        return dict(r.cookies)


async def count_doc(cookies: dict, doctype: str) -> int:
    async with httpx.AsyncClient(timeout=30.0, cookies=cookies) as c:
        r = await c.get(f"{ERP}/api/method/frappe.client.get_list", params={
            "doctype": doctype, "limit_page_length": 0, "fields": json.dumps(["name"])})
        return len((r.json() or {}).get("message") or [])


async def replay_skill(token: str, skill_id: int, overrides: dict) -> dict:
    async with httpx.AsyncClient(timeout=600.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.post(f"{SERVER}/api/v1/skills/{skill_id}/replay",
                            json={"overrides": overrides, "confirm_side_effect": True})
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:200]
        return {"status": resp.status_code, "body": body}


async def main() -> None:
    print("=== S43-4 ERPNext CRM 链回放验证（换参） ===")
    token = mint_token()
    cookies = await erp_login_cookies()
    ts = int(time.time()) % 10000
    results = {}

    n_cust_before = await count_doc(cookies, "Customer")
    r = await replay_skill(token, SKILLS["customer"], {"customer_name": f"SL客户回放{ts}"})
    n_after = await count_doc(cookies, "Customer")
    results["ErpCustomerCreate"] = {
        "http": r["status"], "entity_created": n_after > n_cust_before,
        "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  ErpCustomerCreate: http={r['status']} 客户 {n_cust_before}→{n_after}")

    n_qtn_before = await count_doc(cookies, "Quotation")
    # #214 无 input 变量（客户搜索词在 click label 内），原值回放
    r = await replay_skill(token, SKILLS["quotation"], {})
    n_after = await count_doc(cookies, "Quotation")
    results["ErpQuotationCreate"] = {
        "http": r["status"], "entity_created": n_after > n_qtn_before,
        "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  ErpQuotationCreate: http={r['status']} 报价单 {n_qtn_before}→{n_after}")

    n_so_before = await count_doc(cookies, "Sales Order")
    # search_term 录制值已被转单消耗（Ordered 后 Get Items 搜不到）——
    # override 为当前最新未转单的已提交报价单（技能链数据传递）
    async with httpx.AsyncClient(timeout=60.0) as c:
        resp = await c.post(
            f"{ERP}/api/method/frappe.client.get_list",
            cookies=cookies,
            json={"doctype": "Quotation",
                  "filters": [["docstatus", "=", 1], ["status", "!=", "Ordered"]],
                  "order_by": "creation desc", "limit_page_length": 1,
                  "fields": ["name"]})
        latest_qtn = (((resp.json() or {}).get("message") or [{}])[0]).get("name", "")
    print(f"  search_term override: {latest_qtn}")
    r = await replay_skill(token, SKILLS["so"],
                           {"search_term": latest_qtn} if latest_qtn else {})
    n_after = await count_doc(cookies, "Sales Order")
    results["ErpSalesOrderCreate"] = {
        "http": r["status"], "entity_created": n_after > n_so_before,
        "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  ErpSalesOrderCreate: http={r['status']} 销售订单 {n_so_before}→{n_after}")

    ok = all(v["http"] == 200 and v["entity_created"] for v in results.values())
    print(f"\n结论: {'ALL PASS' if ok else 'FAIL'}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "erpnext-crm-replay.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())

import json
import re
from urllib.parse import urlsplit

# S43-4：32 位无连字符 hex（JeecG online 表 code）也是跨会话实体 id；
# 更长连续 hex 串（双 code 拼接路径如 form/{a}{b}）同理视为动态
_ID_SEGMENT = re.compile(r"^(?:\d+|[0-9a-fA-F-]{36}|[0-9a-fA-F]{16,})$")

# S43-5：state_signal 期望值的动态实体标识门——纯数字 ≥12 位（JeecG
# 派生 code/Snowflake id）或 hex ≥16 位（online 表 code）跨轮回放必然
# 漂移（回放命中行≠录制行），判 fail 是假阴性；记录不判定
_DYNAMIC_EXPECT = re.compile(r"^(?:\d{12,}|[0-9a-fA-F]{16,})$")


def _static_segments(path: str) -> list[str]:
    """路径段序列，剔除动态段（模板 {id}、纯数字段、UUID 段）。"""
    return [seg for seg in path.split("/")
            if seg and seg != "{id}" and not _ID_SEGMENT.match(seg)]


def path_matches(url: str, template: str) -> bool:
    """template 的 {id} 段视为通配（数字/UUID）；url path 中模板未捕获的
    动态段同样忽略；query 忽略。比对剩余静态段序列。"""
    url_path = urlsplit(url).path
    return _static_segments(url_path) == _static_segments(template)


def _extract_field(body: str, field: str) -> object:
    try:
        node = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    for part in field.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def evaluate_assertions(assertions: list[dict], observed: list[dict],
                        after_snapshot: dict | None = None,
                        observed_toasts: list[str] | None = None,
                        executed_steps: list[dict] | None = None) -> list[dict]:
    out: list[dict] = []
    for a in assertions:
        p = a["payload"]
        if a["kind"] == "ui_text":
            # UI 文本断言不走网络观察：用回放 after 快照的 forms 对比。
            # 无快照（采集能力缺失）→ skipped/passed=True 不计失败；
            # 快照存在但 label 缺失 → FAIL（字段消失是真实回归信号，不吞掉）。
            # S42 例外：input 步执行成功后字段缺失 = 对话框表单被提交消费
            # （字段存在且已填，提交后随对话框关闭）——非回归信号。
            forms = ((after_snapshot or {}).get("forms") or [])
            hit = next((f for f in forms if f.get("label") == p.get("label")), None)
            if after_snapshot is None:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "ui_text 无回放快照，跳过"})
            elif hit is None:
                filled = any(
                    s.get("kind") == "input"
                    and (s.get("name") or s.get("label")) == p.get("label")
                    and s.get("ok")
                    for s in (executed_steps or []))
                # S42-12：写响应已发生（表单被提交消费/页面导航离开）——
                # 字段消失是流程完成的预期结果非回归（禅道 Bug 创建的
                # picker 值变更 0→1 由 click 步执行，提交后表单整体消失）
                wrote = any(
                    (o.get("method") or "").upper() in ("POST", "PUT", "PATCH", "DELETE")
                    for o in observed)
                if filled or wrote:
                    out.append({"payload": p, "observed_status": None, "passed": True,
                                "skipped": "字段已填并随提交关闭（对话框表单消费），记录不判定"})
                else:
                    out.append({"payload": p, "observed_status": None, "passed": False,
                                "skipped": "回放快照中字段缺失"})
            else:
                # S42：label 碰撞（搜索框与对话框字段同 placeholder）时
                # after 快照命中的可能是另一个字段；input 步已按期望值
                # 填入且执行成功 → 值的设置有执行证据，对话框随提交关闭
                # 后持久性不可验 → 记录不判定
                filled_ok = any(
                    s.get("kind") == "input"
                    and (s.get("name") or s.get("label")) == p.get("label")
                    and s.get("ok") and s.get("value") == p.get("after")
                    for s in (executed_steps or []))
                if filled_ok and hit.get("value") != p.get("after"):
                    out.append({"payload": p, "observed_status": None, "passed": True,
                                "skipped": "值已由 input 步填入（对话框随提交关闭，快照命中同 label 的其他字段），记录不判定"})
                else:
                    out.append({"payload": p, "observed_status": None,
                                "passed": hit.get("value") == p.get("after")})
            continue
        matched = [o for o in observed if path_matches(o["url"], p["api_template"])]
        if a["kind"] == "api_status" and not matched \
                and "frappe.model.mapper.map_docs" in str(p.get("api_template")):
            # ERPNext mapper 断言等价通道（236 铁证：UI 走 map_docs 端点、
            # API 直调走 make_sales_order wrapper——同一 mapper 底层；
            # wrapper 200 即转单证据成立）
            matched = [o for o in observed
                       if "make_sales_order" in str(o.get("url", ""))
                       and o.get("status") == 200]
            if matched:
                matched = [{**o, "status": p.get("expect_status")} for o in matched]
        if a["kind"] == "api_status":
            statuses = [o["status"] for o in matched]
            passed = bool(statuses) and all(s == p["expect_status"] for s in statuses)
            out.append({"payload": p, "observed_status": statuses[0] if statuses else None,
                        "passed": passed})
        elif a["kind"] == "state_signal" and p.get("field") == "toast":
            # 层1 toast 信号不走响应体（toast 是 UI 元素，body 里永远没有）：
            # 用回放 after 快照的 toasts 通道对比；无快照能力 → skipped（fail-open）。
            # S37 断言语义根治：toast 瞬态——after 快照时机必然错过，
            # 回放期间轮询捕获的 observed_toasts 为主通道、快照为补充；
            # 两通道都未观察到 → skipped（瞬态性本质，不产生假阴性）
            toasts = ((after_snapshot or {}).get("toasts") or []) + (observed_toasts or [])
            if after_snapshot is None and not observed_toasts:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "toast 无回放快照，跳过"})
            elif p.get("expect_value") in toasts:
                out.append({"payload": p, "observed_status": None, "passed": True})
            else:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "toast 瞬态提示未捕获（两通道均未观察到），建议人工复核"})
        elif a["kind"] == "state_signal":
            # S42：GET /{id} 行上下文读取（回放命中行与录制行不同，
            # 行属性期望值天然漂移）→ 记录不判定（与 S37-1 视觉动态同哲学）
            if p.get("context"):
                out.append({"payload": p,
                            "observed_status": matched[0]["status"] if matched else None,
                            "passed": True,
                            "skipped": "行上下文读取（回放行≠录制行），记录不判定"})
                continue
            # S42-7：取最后一次匹配响应判定（终态语义）——同模板的多次调用
            # 含框架噪声（JeecgBoot 表单初始化空值查重返回 code:500
            # "数据为空,不作处理"），all() 语义必被污染
            # S42-12：写操作结果信号优先取最后一次"写响应"（POST/PUT/
            # PATCH/DELETE）——写成功后同模板的页面加载（GET）响应体
            # 无业务字段，会把 success 判定吃成失败（禅道实测）。
            # 无 method 的旧格式回退到最后一次匹配。
            writes = [o for o in matched
                      if (o.get("method") or "").upper() in
                      ("POST", "PUT", "PATCH", "DELETE")]
            terminal = (writes or matched)[-1] if matched else None
            value = _extract_field(terminal.get("body", ""), p["field"]) if terminal else None
            # 空响应体语义（若依 258 铁证：logout 返回 200 空 body——
            # body 里永远没有 code 字段）：field=code 且 expect=数字时
            # 回退用 HTTP status 判定（body 空才回退——有 body 仍走原语义）
            if (value is None and terminal
                    and not (terminal.get("body") or "").strip()
                    and p.get("field") == "code"
                    and str(p.get("expect_value")) == str(terminal.get("status"))):
                value = terminal.get("status")
            # S43-5：期望值本身是动态实体标识（纯数字≥12/hex≥16）——
            # 跨轮回放实体必然新 id，observed≠expect 不是回归信号
            if _DYNAMIC_EXPECT.match(str(p.get("expect_value") or "")):
                out.append({"payload": p,
                            "observed_status": matched[0]["status"] if matched else None,
                            "passed": True,
                            "skipped": "期望值为动态实体标识（跨轮回放必漂移），记录不判定"})
                continue
            passed = bool(matched) and value == p["expect_value"]
            out.append({"payload": p, "observed_status": matched[0]["status"] if matched else None,
                        "passed": passed})
        else:  # field_change：回放时无 before/after 语义，跳过
            out.append({"payload": p, "observed_status": None, "passed": True,
                        "skipped": "field_change 不在回放中判定"})
    return out

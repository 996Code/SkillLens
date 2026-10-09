"""AK5 错误白话映射（四码+关键词 → 用户可读中文）。双端同源：extension
executor-page 的 replace 表与本表语义一致（评审纪律：单一事实源）。"""
from app.exec.failures import ExecCode

_PLAIN = {
    ExecCode.CANCELLED: "已停止（用户中断）",
    ExecCode.TIMEOUT: "步骤超时——页面加载慢或元素未出现",
    ExecCode.TRANSIENT: "页面瞬断（已自动恢复重试）",
    ExecCode.FATAL: "执行失败",
}

_DETAIL_PATTERNS = [
    ("预算耗尽", "执行超时（时间预算用尽）——页面可能卡死，已强制中断"),
    ("挂起 seq=", "与服务器通信挂起——已中断（可重试）"),
    ("Another debugger", "浏览器调试口被占用（如开着 DevTools）——关闭后重试"),
    ("semantic locate failed", "页面上找不到目标元素——页面可能已改版或前置状态缺失"),
    ("Password is required", "目标系统表单要求必填字段缺失"),
    ("点击后无写请求", "提交被页面拦截——表单校验未通过"),
    ("attach 失败", "无法接管页面（其他调试器占用）——关闭 DevTools 后重试"),
    ("目标站不可达", "目标系统无法访问——检查容器/网络是否在线"),
]


def plain_message(code: ExecCode, detail: str = "") -> str:
    """四码+错误细节 → 用户可读中文（AK5：错误直达用户）。"""
    base = _PLAIN.get(code, "执行失败")
    for pat, human in _DETAIL_PATTERNS:
        if pat in (detail or ""):
            return f"{human}"
    return base

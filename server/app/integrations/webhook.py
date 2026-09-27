"""S25 块 W2：Webhook 通知——报告生成/运行完成推送团队工作流。

- WEBHOOK_URL 空 = 关闭（默认）；WEBHOOK_FORMAT：wecom|dingtalk|slack|generic；
- fire-and-forget：推送失败只返回 False + logging，绝不阻塞主流程；
- httpx 依赖已有（server 测试栈同源）。
"""
import logging
import os

import httpx

FORMATS = ("wecom", "dingtalk", "slack", "generic")


def build_payload(fmt: str, title: str, body: str) -> dict:
    """按平台构造消息体；未知格式回落 generic。"""
    if fmt == "wecom":
        return {"msgtype": "markdown", "markdown": {"content": f"## {title}\n{body}"}}
    if fmt == "dingtalk":
        return {"msgtype": "markdown",
                "markdown": {"title": title, "text": f"#### {title}\n{body}"}}
    if fmt == "slack":
        return {"text": f"*{title}*\n{body}"}
    return {"title": title, "body": body}


async def notify(title: str, body: str,
                 transport: httpx.BaseTransport | None = None) -> bool:
    """推送一条通知；URL 未配置或推送失败返回 False（不抛）。"""
    url = os.environ.get("WEBHOOK_URL", "")
    if not url:
        return False
    fmt = os.environ.get("WEBHOOK_FORMAT", "generic")
    payload = build_payload(fmt, title, body)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=5) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code < 300
    except Exception as exc:
        logging.warning("webhook 推送失败: %s", type(exc).__name__)
        return False

"""AF4 flow 解释器：清单 flows → 走查脚本（编排纯函数层）。

录制走查的完整链（af4_record.py 真机用）：manifest 登录（AF3）→
每 flow：插件 START_RECORDING → run_steps 走查（${data} 按轮次注入）→
STOP → 会话交学习管道（process/align/induce，同 s43 模式）。
"""
from app.adapters.manifest import Manifest


def build_flow_script(manifest: Manifest) -> list[dict]:
    """flows → [{flow, steps:[Step...]}]——Step 即六原语（与 login 同构，
    run_steps 直接消费）；${data} 插值位保留，录制轮次时替换。"""
    out: list[dict] = []
    for f in manifest.flows or []:
        out.append({"flow": f.name, "steps": list(f.steps or [])})
    return out

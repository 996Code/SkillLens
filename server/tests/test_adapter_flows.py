"""AF4 flow 解释器：manifest flows 的清单驱动走查录制（TDD）。

语义：flows 里每条 flow = 登录后经 run_steps 走查（期间插件采集会话
包裹）→ 会话交学习管道。本测试聚焦编排纯函数部分：
- build_flow_script(manifest) → 逐 flow 的原语序列（含 ${data} 插值位）
- 录制会话包裹（START/STOP 语义由编排器对齐 s43 模式）
真机走查在 AF4 收口用 af4_record.py 验（依赖 9222+8710）。
"""
from pathlib import Path

from app.adapters.manifest import load_manifest_text
from app.adapters.flows import build_flow_script


ZENTAO_FLOWS = """
id: zentao
label: 禅道
target: {base_url: "http://127.0.0.1:8082"}
credentials: {username: admin, password_literal: pw}
login:
  steps: [{goto: /login}]
probes:
  - id: story_count
    kind: http
    request: {method: GET, url: "${base_url}/api/status"}
    assert: {status: 200}
flows:
  - name: ZentaoStoryCreate
    steps:
      - goto: /index.php?m=story&f=create&productID=1
      - routine: close_guide
      - fill: ["input[name=title]", "${data}"]
      - routine: biz_frame_submit
  - name: ZentaoCaseRun
    steps:
      - goto: /index.php?m=testcase&f=browse&productID=1
      - routine: close_guide
      - click: "a[title=执行]"
"""


def test_build_flow_script_expands_primitives():
    m, _ = load_manifest_text(ZENTAO_FLOWS)
    scripts = build_flow_script(m)
    assert [s["flow"] for s in scripts] == ["ZentaoStoryCreate", "ZentaoCaseRun"]
    first = scripts[0]["steps"]
    ops = [s.op for s in first]
    assert ops == ["goto", "routine", "fill", "routine"]
    assert first[2].arg2 == "${data}"  # 数据插值位保留（录制轮次注入）
    assert first[3].arg == "biz_frame_submit"


def test_build_flow_script_empty_flows_ok():
    doc = ZENTAO_FLOWS.split("flows:")[0]
    m, _ = load_manifest_text(doc)
    assert build_flow_script(m) == []

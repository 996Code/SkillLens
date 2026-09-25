# 块 P 公网站点泛化实测验收记录（主计划 v1.4）

日期：2026-09-25。目标：新浪搜索（search.sina.com.cn，antd 技术栈）——完全陌生的公网系统。
百度被浏览器拒（反爬/TLS 指纹，commit 都超时；curl 通）→ 换新浪。

## 核心成果：陌生系统完整闭环

```
3 会话采集（低代码/人工智能/软件测试）
→ process：每会话 9 事件（action 2/nav 1/network 4/snapshot 2）→ 1 窗口 1 语义动作
  锚点"搜 索" ✓ | API 模板化 /api/search 等 ✓ | 状态信号 code=0（新浪约定）✓
→ align：1 桶 1 步，变量 rc_select_0={低代码,人工智能,软件测试} ✓
→ induce（真实 LLM）：ExecuteSearch / "用户输入或选择关键字并执行搜索操作" conf 1.0
→ 断言 6→5 条（重建后）全 verify PASS
→ 换参回放（"大模型"）：**PASS 5/5**，搜索框值="大模型"（搜索真实执行）
```

## 实测抓出的 3 个真 bug（全部已修 + 232 全绿）

| # | Bug | 根因 | 修复 |
|---|---|---|---|
| P-1 | **S13 重构连接生命周期**：真实 execute 回放必 error（"browser has been closed"）——S13 后所有回放是 shadow/Fake，单测全绿掩盖 | `async with _launch()` 块在开完浏览器即退出，Playwright 连接断，执行在 with 外用死浏览器 | run_replay/run_replay_batch 执行整体移回 with 块内 |
| P-2 | 框架自动生成 id 定位失败：antd 输入框无 placeholder 在 input 元素上，采集回退链抓到 `rc_select_0`（跨会话不稳定） | locate 无 id 兜底策略 | locate 加 `#id` 兜底（排在语义策略后） |
| P-3 | ui_text 双语义洞：①被覆盖变量的期望还是录制值（换参必 FAIL）②空 label 字段生成无意义断言 | 生成/评估侧未考虑覆盖与空 label | 覆盖值跟随注入值；空 label 跳过生成 |

## 泛化结论（G5 语料）

- **管道对陌生系统鲁棒**：URL 模板化/窗口切分/信号提取/对齐/变量识别零改动通过
- 语义定位依赖目标系统的可访问性质量（placeholder/aria）——无语义元素时回退 id（不稳定），**采集侧 input-key 链应跳过框架生成 id**（rc_select_N 模式）→ 列入块 L 前置
- 第二系统语料就位：njmind（表单保存/查询）+ 新浪（搜索）= **2 个任务族**——G5 闸口的"≥2 任务族"已满足，"第二系统"从"最好有"变为已验证

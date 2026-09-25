# SkillLens 发版验收 SOP（S11 / 块 E1）

> 适用：明搭云（192.168.99.22）真实发版的四分类验收。每次发版照此执行，产物入 demo/sprint11/。

## 发版闭环八步

```
1. 需求记录     发版前把需求文本写定（一句话+验收要点）
2. Expected     POST /expected-deltas {requirement_id, requirement_text}
                → LLM draft → 人工 confirm 修订（模板对齐观测形态：/codeBack 前缀等）
3. 真实变更     在明搭云上实施变更（用户或授权 Agent 操作，常驻窗口可见）
4. 新流量采集   变更后操作一次受影响功能（RECORD_CDP_URL 录制，real_traffic）
5. Observe      POST /expected-deltas/{id}/observe {skill_id, overrides, confirm_side_effect:true}
                → 常驻窗口真实回放
6. Report       POST /expected-deltas/{id}/report {observed_delta_id}
                → 四分类（工作台 /reports/{id} 查看）
7. 证据链       /audit 页核对：会话→窗口→语义动作→对齐→回放 全链
8. 评审归档     报告+截图+评审结论入 demo/sprint11/release-N.md，团队核签
```

## 观察项（v1.3 新增，每发版记录）

- **N1 新功能发现行为**：变更含新功能时，记录系统对新 UI 元素/新 API 的发现表现（当前机制边界：回放路径外的功能不出现在 observed——这是块 N 的立项依据）。
- **回归面**：不应该变的有没有被破坏（既有 Skill 回放是否仍 PASS）。

## 验收口径（M2 出口）

- 两次真实发版，四分类准确（Expected/Missing/Unexpected 真实可解释，Drift 如有时序数据）
- 报告在工作台呈现，团队评审核签"有行动价值"

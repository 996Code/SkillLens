# zcode 源码二次深读（2026-10-08，多 agent 学习第 5 路）

> 第一次学习产物见 zcode-browser-harness-study.md（五层架构+差距表 10 项）。
> 本轮挖第一次的盲区。zcode 源码位置：/d/github/zcode-src/packages/desktop/src/main/browserView/

## 二次学习新发现（13 条，P0/P1/P2 分级）

### 核心机制（带行级证据）

1. **可见收窄唯一性**（browserPlaywrightLocatorExecutor.ts L21-42）：候选不唯一时
   按"可见性"收窄再判唯一——比我们的"唯一命中才用"多了中间态。
2. **按操作定制 actionability**（L295-322）：click/fill/hover 各有独立的
   可交互性检查组合——我们目前一套通吃。
3. **document race 恢复**（L139-144/326-337）：document 被导航替换时的
   上下文失效恢复。
4. **raceActionProbe 双层超时+terminateExecution**（L729-775）：探针超时
   后主动终止执行流，不是无限等待。
5. **requireActionProbe payload 校验**（L641-671）：探针返回数据结构的
   schema 校验（防页面脚本伪造）。
6. **FrameBoundary 插值链**（L673-727/891-968）：跨 frame 定位的帧边界
   编码——iframe 嵌套定位的系统解法。
7. **错误三码分类**（browserPlaywrightExecutor.ts L143-154）：
   cancelled/timeout/execution_error 三码 + 带行动指引的超时消息
   （browserCommandExecutor.ts L113-133）——与 SkillLens 异常分类学
   （E1-E4）设计同族，可直接借鉴其"错误消息=分类键+人话行动指引"。
8. **elementInfoRuntime 候选选择器**（L18-62）：识别时的多候选输出。
9. **inputTargetToken 双重验证**（browserVirtualClipboard.ts L231-255 /
   页面侧 71-75）：虚拟剪贴板的目标 token 两侧校验。
10. **resolveFocusedTarget 焦点帧循环防护**（L135）。
11. **confirmAbortedNavigationCommitted 四重确认**
    （browserCommandPageHandlers.ts L135-166）：导航中断后的提交确认
    链——比我们的两步提交豁免更严谨。
12. **瞬态分类有界退避**（browserScreenshotTransientRetry.ts，62 行全文）：
    截图失败的瞬态/永久分类+有界重试——我们截图是 fail-open 直接丢。
13. **guestManager 4639 行未学习**：tab 常驻/CDP 会话恢复/录制可视化
    ——第三轮学习候选。

### 对 SkillLens 的直接建议（按优先级）

- **P0**：错误三码+行动指引消息（喂异常分类学 E1-E4 的签名表）；
  瞬态分类有界退避（截图重试，替代 fail-open）。
- **P1**：按操作定制 actionability（click/fill 分道）；可见收窄唯一性
  （定位中间态）；FrameBoundary 插值链（禅道 iframe 深嵌套）。
- **P2**：探针 payload schema 校验；四重导航确认；guestManager 三轮。

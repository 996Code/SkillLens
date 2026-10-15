import { defineManifest } from "@crxjs/vite-plugin";

export default defineManifest({
  manifest_version: 3,
  name: "SkillLens Sensor",
  version: "0.3.1",
  // S42：<all_urls>——chrome.scripting.executeScript 注入子 frame 需要
  // 对应 host 权限（与 content_scripts 的 <all_urls> 匹配范围一致）
  host_permissions: ["http://127.0.0.1:8710/*", "<all_urls>"],
  // S42：scripting+webNavigation——动态创建的 about:blank iframe（禅道综合
  // 界面等）不会自动注入 content script，须 SW 程序化注入子 frame
  // AG3：debugger+tabs——扩展执行器（chrome.debugger CDP 可信输入+tab 枚举）
  permissions: ["alarms", "storage", "scripting", "webNavigation", "debugger", "tabs"],
  action: { default_popup: "popup.html" },
  // AG3：执行页经 options_ui 引用进构建（CRXJS 只转译 manifest 功能入口；
  // 实际访问形态=chrome-extension://…/executor.html?skill=N 独立 tab）
  options_ui: { page: "executor.html", open_in_tab: true },
  // S42：all_frames——禅道 22 综合界面等 iframe 架构应用把业务内容渲染在
  // about:blank iframe 里，顶层注入采集不到任何事件
  content_scripts: [
    { matches: ["<all_urls>"], js: ["src/content/capture.ts"], all_frames: true },
    // AH4b 悬浮面板：常驻注入但懒挂载（零 UI，直到 skilllens:show-space 事件）
    // ——CRXJS 只编译 manifest 声明的 CS 文件，动态 executeScript files
    // 引用 TS 源路径不编译（实锤：dist 无产物、注入静默失败）
    { matches: ["<all_urls>"], js: ["src/content/space-panel.ts"], run_at: "document_idle" },
  ],
  background: { service_worker: "src/background/uploader.ts", type: "module" },
  // 注：CRXJS 对 web_accessible_resources 条目按原样复制（不做 TS→JS 转换），
  // 故该入口必须是纯 JS 文件（src/injected/net-hook.js）。
  web_accessible_resources: [
    { resources: ["src/injected/net-hook.js"], matches: ["<all_urls>"] },
    // AH6：executor/learn 页声明 web accessible——面板（content script 的
    // window.open）打开扩展页不再被 ERR_BLOCKED_BY_CLIENT 拦；页面带
    // token 参数自证身份（无鉴权页面本身不含敏感数据）
    { resources: ["executor.html", "learn.html"], matches: ["<all_urls>"] },
  ],
});

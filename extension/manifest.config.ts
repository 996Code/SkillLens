import { defineManifest } from "@crxjs/vite-plugin";

export default defineManifest({
  manifest_version: 3,
  name: "SkillLens Sensor",
  version: "0.1.0",
  host_permissions: ["http://127.0.0.1:8710/*"],
  permissions: ["alarms"],
  content_scripts: [{ matches: ["<all_urls>"], js: ["src/content/capture.ts"] }],
  background: { service_worker: "src/background/uploader.ts", type: "module" },
  // 注：CRXJS 对 web_accessible_resources 条目按原样复制（不做 TS→JS 转换），
  // 故该入口必须是纯 JS 文件（src/injected/net-hook.js）。
  web_accessible_resources: [{ resources: ["src/injected/net-hook.js"], matches: ["<all_urls>"] }],
});

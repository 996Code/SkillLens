import { defineManifest } from "@crxjs/vite-plugin";

export default defineManifest({
  manifest_version: 3,
  name: "SkillLens Sensor",
  version: "0.1.0",
  host_permissions: ["http://127.0.0.1:8710/*"],
  content_scripts: [{ matches: ["<all_urls>"], js: ["src/content/capture.ts"] }],
  background: { service_worker: "src/background/uploader.ts", type: "module" },
});

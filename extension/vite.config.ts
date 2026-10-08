import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.config";

export default defineConfig({
  plugins: [crx({ manifest })],
  build: {
    // AH4 空间小窗：非 manifest 功能入口的扩展页（chrome.windows.create 打开）
    // 需要显式 rollup 入口，否则 CRXJS 不转译不产出
    rollupOptions: { input: { space: "space.html", learn: "learn.html" } },
  },
});

import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 生产构建产物交由 FastAPI StaticFiles 挂载（app/main.py），
// dev 模式 /api 代理到本机 8710（正式 server），API base 保持相对路径零配置。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8710",
        changeOrigin: true,
      },
    },
  },
});

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

// CogEdu 前端工程配置，移植自 ECOS v0.99.5 前端（../ecos/web/frontend/，只读复制自包含维护）。
// 托管衔接：构建产物 dist/ 由 web/api/routers/static_pages.py 托管（dist 优先、legacy 静态页兜底），
// 三入口名 index.html(教师) / student.html / parent.html 与 static_pages 的 DIST_DIR 约定对齐。
// dev: Vite 5174，proxy /api → FastAPI 5173；生产由 FastAPI 同源托管，代码内 API base 恒为相对路径 /api。
// __APP_VERSION__ 编译期注入 package.json version（沿用 ECOS 防硬编码版本的教训）。
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react()],
  base: "./",
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5173",
        changeOrigin: true,
      },
      // dev 模式下 vanilla 模块与 KaTeX vendor 仍由 FastAPI 提供（生产同源）
      "/student": {
        target: "http://127.0.0.1:5173",
        changeOrigin: true,
      },
      "/vendor": {
        target: "http://127.0.0.1:5173",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      // 多页 — teacher SPA (index.html) + student SPA (student.html) + parent SPA (parent.html)
      input: {
        teacher: "index.html",
        student: "student.html",
        parent: "parent.html",
      },
      output: {
        manualChunks: {
          // 拆 echarts / react 独立 chunk, 避免单包过大（首屏可缓存）
          echarts: ["echarts"],
          vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
        },
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "../index.css";

// 家长端无 <Routes>（单页，列表/详情靠 ?student= query 切换），但
// HashRouter 必须保留：ParentHomePage 的 useSearchParams 需要 Router
// 上下文，缺失 = 整树抛异常白屏（2026-09-15 验收发现，ECOS 原版即有）。
const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 15_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  </StrictMode>,
);

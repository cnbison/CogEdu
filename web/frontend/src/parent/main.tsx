import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "../AppShell";
import "../index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppShell title="CogEdu 家长端" />
  </StrictMode>,
);

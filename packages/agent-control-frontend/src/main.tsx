import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/global.css";
import { readPreference } from "./session/workspaceUiStore";

document.documentElement.dataset.theme =
  readPreference("theme", "dark") === "light" ? "light" : "dark";

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

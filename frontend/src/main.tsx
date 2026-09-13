import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import UpdateCenter from "./UpdateCenter";
import { I18nProvider } from "./i18n";
import "./style.css";
import "./motion.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <I18nProvider>
      <App />
      <UpdateCenter />
    </I18nProvider>
  </React.StrictMode>,
);

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
export default defineConfig({
  plugins: [
    react(),
    {
      name: "local-pdf-resources",
      closeBundle() {
        const notices = ["react", "react-dom", "scheduler", "lucide-react", "pdfjs-dist"]
          .map((name) => `${name}\n${"=".repeat(72)}\n${readFileSync(`node_modules/${name}/LICENSE`, "utf8")}`)
          .join("\n\n");
        writeFileSync("dist/THIRD_PARTY_LICENSES.txt", notices, "utf8");
        for (const folder of ["cmaps", "standard_fonts", "wasm"]) {
          mkdirSync(`dist/pdfjs/${folder}`, { recursive: true });
          cpSync(`node_modules/pdfjs-dist/${folder}`, `dist/pdfjs/${folder}`, {
            recursive: true,
          });
        }
      },
    },
  ],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { chunkSizeWarningLimit: 800 },
});

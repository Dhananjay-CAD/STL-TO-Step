import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// Dev showcase of the components (npm run dev). The dashboard itself uses
// scripts/build-dashboard.mjs, which bundles src/dashboard-entry.tsx.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
})

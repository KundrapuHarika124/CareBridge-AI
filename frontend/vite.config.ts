/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the frontend calls /api on its own origin and Vite forwards it to the
// backend, mirroring the production rewrite. Cookies therefore stay first-party.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_DEV_BACKEND ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});

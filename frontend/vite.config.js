import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api calls go to the FastAPI backend, so the app needs no CORS setup.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8001" } },
});

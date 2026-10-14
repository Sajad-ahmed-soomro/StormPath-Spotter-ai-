import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      // Dev only: forward /api to the Django server named in frontend/.env.
      proxy: env.VITE_DEV_API_PROXY ? { "/api": env.VITE_DEV_API_PROXY } : undefined,
    },
    build: { outDir: "dist", sourcemap: false },
  };
});

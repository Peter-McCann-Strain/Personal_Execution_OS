import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  test: {
    env: {
      VITE_ALLOW_INSECURE_DEV_AUTH: "true",
    },
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.tsx"],
    css: true,
    testTimeout: 10000,
    include: ["tests/**/*.{test,spec}.{ts,tsx}", "src/**/__tests__/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      all: true,
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/vite-env.d.ts", "src/api/generated/**", "src/types/**"],
      reporter: ["text", "html", "json-summary"],
      thresholds: {
        statements: 94,
        branches: 90,
        functions: 94,
        lines: 95,
      },
    },
  },
});

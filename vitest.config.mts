import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Vitest runs the dashboard's unit tests: the pure stream reducer and format
 * helpers, and the two components whose live behaviour the demo leans on
 * (the counter's rupee formatting and the audit table's append ordering).
 *
 * The `@/` alias mirrors `tsconfig.json` so tests import modules exactly as the
 * app does, and jsdom + the React plugin let the component tests render real DOM.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

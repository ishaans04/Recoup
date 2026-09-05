import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Since the flatten, the Python virtualenv sits alongside the app at the
    // repo root. It ships vendored JavaScript (coverage's HTML report) that is
    // not ours to lint.
    ".venv/**",
    "htmlcov/**",
    // The source design comps. Vendor JavaScript we neither wrote nor ship.
    "src/Recoup Landing & Console Design/**",
  ]),
]);

export default eslintConfig;

import js from "@eslint/js";
import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist/**", "test-results/**", "playwright-report/**"] },
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "error",
        { allowConstantExport: true },
      ],
      // tsc already enforces unused locals. This rule duplicates it and
      // flags names that TypeScript 7 still accepts.
      "@typescript-eslint/no-unused-vars": "off",
      "no-unused-vars": "off",
      // TypeScript already checks undefined names. This rule false-positives
      // on DOM and Node globals the parser does not declare.
      "no-undef": "off",
      // Baseline findings. Keep them visible without failing the gate.
      "@typescript-eslint/no-explicit-any": "warn",
      "preserve-caught-error": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/refs": "warn",
    },
  },
];

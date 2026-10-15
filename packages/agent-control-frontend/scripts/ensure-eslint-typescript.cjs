/**
 * typescript-eslint 8 parses with the TypeScript 6 API and refuses TypeScript 7.
 * The app compiler stays on TypeScript 7. Point the ESLint packages at the
 * side-by-side typescript-6 install before they resolve "typescript".
 */
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const source = path.join(root, "node_modules", "typescript-6");
const parents = [
  ["@typescript-eslint"],
  ["ts-api-utils"],
  ["typescript-eslint"],
];

if (!fs.existsSync(path.join(source, "package.json"))) {
  console.error("typescript-6 is not installed. Run npm install in packages/agent-control-frontend.");
  process.exit(1);
}
for (const parts of parents) {
  const target = path.join(root, "node_modules", ...parts, "node_modules", "typescript");
  if (fs.existsSync(path.join(target, "package.json"))) continue;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.symlinkSync(source, target, "junction");
}

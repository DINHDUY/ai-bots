import { compileFromFile } from "json-schema-to-typescript";
import { writeFile } from "node:fs/promises";
const source = new URL("../src/api/events.schema.json", import.meta.url);
const target = new URL("../src/api/events.generated.ts", import.meta.url);
await writeFile(target, await compileFromFile(source.pathname.replace(/^\/(\w:)/, "$1"), {
  bannerComment: "/* Generated from events.schema.json; run npm run generate:wire. */",
  additionalProperties: false,
}));
const imports = new URL("../src/api/imports.schema.json", import.meta.url);
await writeFile(new URL("../src/api/imports.generated.ts", import.meta.url),
  await compileFromFile(imports.pathname.replace(/^\/(\w:)/, "$1"), {
    bannerComment: "/* Generated from imports.schema.json; run npm run generate:wire. */",
    additionalProperties: false,
    ignoreMinAndMaxItems: true,
  }));

const deletions = new URL("../src/api/deletions.schema.json", import.meta.url);
await writeFile(new URL("../src/api/deletions.generated.ts", import.meta.url),
  await compileFromFile(deletions.pathname.replace(/^\/(\w:)/, "$1"), {
    bannerComment: "/* Generated from deletions.schema.json; run npm run generate:wire. */",
    additionalProperties: false,
    ignoreMinAndMaxItems: true,
  }));

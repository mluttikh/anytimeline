// The scene spec's JSON Schema, generated from types.ts (npm run schema), is what Python's
// specs are checked against (tests/test_spec_contract.py): it must be that of types.ts now.

import { readFileSync } from "node:fs";
import { createGenerator } from "ts-json-schema-generator";
import { describe, expect, it } from "vitest";

describe("the scene spec's schema", () => {
  it("is up to date with types.ts (else: npm run schema)", () => {
    const schema = createGenerator({ path: "src/core/types.ts", type: "SceneSpec", tsconfig: "tsconfig.json" }).createSchema("SceneSpec");
    const committed = JSON.parse(readFileSync("../tests/fixtures/scene-schema.json", "utf8"));
    expect(schema).toEqual(committed);
  }, 60_000);
});

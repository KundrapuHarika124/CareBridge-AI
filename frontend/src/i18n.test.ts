import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import te from "./locales/te.json";

type Tree = { [key: string]: string | Tree };

function flatten(node: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(node)) {
    if (typeof value === "string") out[prefix + key] = value;
    else Object.assign(out, flatten(value, `${prefix}${key}.`));
  }
  return out;
}
const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(",");

describe("translations", () => {
  const english = flatten(en as Tree);
  const telugu = flatten(te as Tree);

  it("has the same keys in Telugu and English", () => {
    expect(Object.keys(telugu).sort()).toEqual(Object.keys(english).sort());
  });

  it("uses the same placeholders in both languages", () => {
    for (const key of Object.keys(english)) {
      expect(placeholders(telugu[key] ?? ""), key).toBe(placeholders(english[key]));
    }
  });

  it("has no empty text", () => {
    for (const [key, value] of [...Object.entries(english), ...Object.entries(telugu)]) {
      expect(value.trim().length, key).toBeGreaterThan(0);
    }
  });
});

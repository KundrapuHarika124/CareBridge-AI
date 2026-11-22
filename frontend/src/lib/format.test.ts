import { describe, expect, it } from "vitest";
import { groupByDay, istDate, pickName, rupees } from "./format";

describe("format helpers", () => {
  it("converts a UTC instant to the IST calendar date", () => {
    expect(istDate("2026-11-20T19:00:00Z")).toBe("2026-11-21"); // 00:30 IST next day
    expect(istDate("2026-11-20T05:00:00Z")).toBe("2026-11-20");
  });
  it("groups slots by IST day in order", () => {
    const slots = [{ starts_at: "2026-11-20T05:00:00Z" }, { starts_at: "2026-11-20T06:00:00Z" }, { starts_at: "2026-11-20T19:00:00Z" }];
    const groups = groupByDay(slots);
    expect(groups.map(([day, items]) => [day, items.length])).toEqual([["2026-11-20", 2], ["2026-11-21", 1]]);
  });
  it("picks the name for the language and formats rupees", () => {
    expect(pickName({ name_en: "Cardiology", name_te: "గుండె వైద్యం" }, "te")).toBe("గుండె వైద్యం");
    expect(rupees(500)).toBe("₹500");
    expect(rupees(null)).toBe("");
  });
});

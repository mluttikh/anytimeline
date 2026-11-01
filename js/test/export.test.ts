import { describe, expect, it } from "vitest";
import { byteSize, exportEntries, fileName, LARGE_SVG_BYTES, svgCopiedMessage } from "../src/core/export";

const hows = (can: Parameters<typeof exportEntries>[0]) => exportEntries(can).map((e) => e.how);

describe("the Export menu", () => {
  it("offers everything in a notebook on a secure page in Chromium", () => {
    expect(hows({ copyImages: true, copySvg: true, svg: true, save: true })).toEqual(["copy", "copy-svg", "png", "svg", "save-png", "save-svg"]);
  });

  it("leaves out copying SVG where the browser cannot (Firefox, Safari)", () => {
    expect(hows({ copyImages: true, copySvg: false, svg: true, save: true })).toEqual(["copy", "png", "svg", "save-png", "save-svg"]);
  });

  it("leaves out copying on a page that is not secure (plain http)", () => {
    expect(hows({ copyImages: false, copySvg: false, svg: true, save: true })).toEqual(["png", "svg", "save-png", "save-svg"]);
  });

  it("offers the PNG only in a saved page: no Python to draw an SVG or write a file", () => {
    expect(hows({ copyImages: true, copySvg: true, svg: false, save: false })).toEqual(["copy", "png"]);
    expect(hows({ copyImages: false, copySvg: false, svg: false, save: false })).toEqual(["png"]);
  });

  it("names every entry and says what it gives", () => {
    for (const e of exportEntries({ copyImages: true, copySvg: true, svg: true, save: true })) {
      expect(e.label.length).toBeGreaterThan(3);
      expect(e.note.length).toBeGreaterThan(3);
    }
  });
});

describe("file names and sizes", () => {
  it("names a file after the title", () => {
    expect(fileName("Checkout · trace #42", "svg")).toBe("checkout-trace-42.svg");
    expect(fileName("  ", "png")).toBe("timeline.png");
    expect(fileName("Größe über Zeit", "png")).toBe("größe-über-zeit.png");
  });

  it("says when a copied SVG is large", () => {
    expect(byteSize(1500)).toBe("2 kB");
    expect(byteSize(2_500_000)).toBe("2.5 MB");
    expect(svgCopiedMessage(40_000)).toBe("Copied as SVG (40 kB): paste it into your slides");
    expect(svgCopiedMessage(LARGE_SVG_BYTES + 1)).toMatch(/large, so slow in slides/);
  });
});

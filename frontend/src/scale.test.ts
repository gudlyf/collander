import { describe, expect, it } from "vitest";
import { formatNumber, parseNumber, scaleLine, scaleServings } from "./scale";

describe("parseNumber", () => {
  it.each([
    ["2", 2],
    ["1.5", 1.5],
    ["1,5", 1.5],
    ["1/2", 0.5],
    ["1 1/2", 1.5],
    ["1-1/2", 1.5],
    ["½", 0.5],
    ["1½", 1.5],
    ["1 ½", 1.5],
  ])("%s -> %d", (s, n) => expect(parseNumber(s)).toBeCloseTo(n));
});

describe("formatNumber", () => {
  it.each([
    [1, "1"],
    [0.5, "½"],
    [1.5, "1½"],
    [0.333, "⅓"],
    [2.6667, "2⅔"],
    [0.125, "⅛"],
    [1.1, "1.1"],
    [12.25, "12¼"],
    [0.999, "1"],
  ])("%d -> %s", (n, s) => expect(formatNumber(n)).toBe(s));
});

describe("scaleLine", () => {
  it("doubles simple quantities", () => {
    expect(scaleLine("2 cups flour", 2).text).toBe("4 cups flour");
    expect(scaleLine("1/2 tsp salt", 2).text).toBe("1 tsp salt");
    expect(scaleLine("1 1/2 lb tomatoes", 2).text).toBe("3 lb tomatoes");
    expect(scaleLine("½ cup sugar", 3).text).toBe("1½ cup sugar");
  });
  it("treats hyphenated mixed numbers as one quantity", () => {
    expect(scaleLine("1-1/2 cups flour", 2).text).toBe("3 cups flour");
    expect(scaleLine("2-1/4 tsp yeast", 2).text).toBe("4½ tsp yeast");
    expect(scaleLine("1-2 tsp chili flakes", 2).text).toBe("2-4 tsp chili flakes");
  });
  it("halves", () => {
    expect(scaleLine("3 eggs", 0.5).text).toBe("1½ eggs");
    expect(scaleLine("1 cup milk", 0.5).text).toBe("½ cup milk");
  });
  it("scales ranges", () => {
    expect(scaleLine("2-3 cloves garlic", 2).text).toBe("4-6 cloves garlic");
    expect(scaleLine("2 to 3 tbsp oil", 2).text).toBe("4 to 6 tbsp oil");
  });
  it("keeps the rest of the line intact", () => {
    expect(scaleLine("1 (14 oz) can tomatoes", 2).text).toBe("2 (14 oz) can tomatoes");
  });
  it("leaves lines without a leading quantity alone", () => {
    const r = scaleLine("Salt to taste", 2);
    expect(r.text).toBe("Salt to taste");
    expect(r.scaled).toBe(false);
    expect(scaleLine("Juice of 1 lemon", 2).text).toBe("Juice of 1 lemon");
  });
  it("is a no-op at 1x", () => {
    expect(scaleLine("2 cups flour", 1)).toEqual({ text: "2 cups flour", scaled: false, qtyEnd: 0 });
  });
});

describe("scaleServings", () => {
  it("scales the first number", () => {
    expect(scaleServings("Serves 4", 2)).toBe("Serves 8");
    expect(scaleServings("4-6 servings", 2)).toBe("8-12 servings");
    expect(scaleServings("a crowd", 2)).toBe("a crowd");
  });
});

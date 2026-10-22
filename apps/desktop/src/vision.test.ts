import { describe, expect, it } from "vitest";
import { base64Image, MAX_IMAGE_BYTES, validImage } from "./vision";
describe("image ingress", () => {
  it("bounds files and rejects unsupported types", () => {
    expect(validImage({ size: 100, type: "image/png" })).toBe(true);
    expect(validImage({ size: 0, type: "image/png" })).toBe(false);
    expect(validImage({ size: MAX_IMAGE_BYTES + 1, type: "image/jpeg" })).toBe(false);
    expect(validImage({ size: 100, type: "image/svg+xml" })).toBe(false);
  });
  it("encodes exact bytes, including multiple chunks", () => {
    const bytes = new Uint8Array(70000); bytes[35000] = 255;
    const decoded = atob(base64Image(bytes));
    expect(decoded.length).toBe(bytes.length);
    expect(decoded.charCodeAt(35000)).toBe(255);
    expect(() => base64Image(new Uint8Array())).toThrow();
  });
});

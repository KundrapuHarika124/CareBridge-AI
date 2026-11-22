import { describe, expect, it } from "vitest";
import { isBrowserRecognitionSupported, isBrowserSpeechSupported, isBrowserSynthesisSupported } from "./speech";

describe("browser speech support", () => {
  it("falls back safely when browser APIs are unavailable", () => {
    expect(isBrowserRecognitionSupported()).toBe(false);
    expect(isBrowserSynthesisSupported()).toBe(false);
    expect(isBrowserSpeechSupported()).toBe(false);
  });
});

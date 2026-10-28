import { afterEach, expect, it, vi } from "vitest";
import { operationId } from "./operation-id";

afterEach(() => vi.unstubAllGlobals());

it("generates distinct version-4 UUIDs when randomUUID is unavailable", () => {
  vi.stubGlobal("crypto", {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  });
  const ids = Array.from({ length: 1000 }, () => operationId());
  expect(new Set(ids).size).toBe(ids.length);
  for (const id of ids) {
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  }
});

it("uses the browser UUID implementation when available", () => {
  const id = "ed96af63-217a-4c44-81e1-2b3ded15899e";
  vi.stubGlobal("crypto", { randomUUID: () => id });
  expect(operationId()).toBe(id);
});

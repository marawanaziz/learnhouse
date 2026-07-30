import { describe, expect, test } from "bun:test";

import { resolveResumePosition } from "../services/media/videoProgress.ts";

describe("resolveResumePosition", () => {
  test("restores an in-progress video", () => {
    expect(
      resolveResumePosition({
        savedPosition: 72.5,
        duration: 180,
      })
    ).toBe(72.5);
  });

  test("starts a new video from the beginning", () => {
    expect(
      resolveResumePosition({
        savedPosition: 0,
        duration: 180,
      })
    ).toBe(0);
  });

  test("restarts a finished video instead of reopening on the final frame", () => {
    expect(
      resolveResumePosition({
        savedPosition: 178,
        duration: 180,
      })
    ).toBe(0);
  });

  test("honors configured start and end bounds", () => {
    expect(
      resolveResumePosition({
        savedPosition: 5,
        duration: 180,
        startTime: 15,
        endTime: 120,
      })
    ).toBe(15);
    expect(
      resolveResumePosition({
        savedPosition: 80,
        duration: 180,
        startTime: 15,
        endTime: 120,
      })
    ).toBe(80);
  });

  test("ignores invalid or tiny checkpoints", () => {
    expect(
      resolveResumePosition({
        savedPosition: Number.NaN,
        duration: 180,
        startTime: 10,
      })
    ).toBe(10);
    expect(
      resolveResumePosition({
        savedPosition: 2,
        duration: 180,
      })
    ).toBe(0);
  });
});

import { DEFAULT_MANUAL_SECONDS, DEFAULT_RESPONSE_TIMEOUT_MS, DEFAULT_URL } from "./constants.js";
import type { CliOptions } from "./types.js";

function readBooleanFlag(args: string[], name: string): boolean {
  return args.includes(name);
}

function readValue(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  if (index === -1) {
    return undefined;
  }

  return args[index + 1];
}

export function parseCliArgs(argv: string[]): CliOptions {
  const url = readValue(argv, "--url") ?? DEFAULT_URL;
  const keyword = readValue(argv, "--keyword");
  const responseTimeoutMs = Number(readValue(argv, "--response-timeout") ?? DEFAULT_RESPONSE_TIMEOUT_MS);
  const manualSeconds = Number(readValue(argv, "--manual-seconds") ?? DEFAULT_MANUAL_SECONDS);

  if (!url.startsWith("http")) {
    throw new Error("参数 --url 必须是完整的 http 或 https 地址。");
  }

  if (!Number.isFinite(responseTimeoutMs) || responseTimeoutMs <= 0) {
    throw new Error("参数 --response-timeout 必须是正整数。");
  }

  if (!Number.isFinite(manualSeconds) || manualSeconds <= 0) {
    throw new Error("参数 --manual-seconds 必须是正整数。");
  }

  return {
    url,
    headed: readBooleanFlag(argv, "--headed"),
    keyword,
    responseTimeoutMs,
    manualSeconds
  };
}

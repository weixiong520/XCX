import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

export const storageDir = path.resolve("storage");
export const outputDir = path.resolve("output", "latest");

export async function ensureProjectDirs(): Promise<void> {
  await mkdir(storageDir, { recursive: true });
  await mkdir(outputDir, { recursive: true });
}

export async function writeJson(filePath: string, value: unknown): Promise<void> {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

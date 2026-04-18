import { access } from "node:fs/promises";
import { parseCliArgs } from "./cli.js";
import { ensureProjectDirs } from "./fs.js";
import { authStatePath, fetchDeadline } from "./wechat.js";

async function main(): Promise<void> {
  const options = parseCliArgs(process.argv.slice(2));
  await ensureProjectDirs();
  try {
    await access(authStatePath);
  } catch {
    throw new Error("未找到 storage/auth.json，请先执行 `npm run auth -- --url https://mp.weixin.qq.com/` 保存登录态。");
  }
  const result = await fetchDeadline(options);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`抓取失败：${message}\n`);
  process.exitCode = 1;
});

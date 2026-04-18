import { parseCliArgs } from "./cli.js";
import { ensureProjectDirs } from "./fs.js";
import { saveAuthState } from "./wechat.js";

async function main(): Promise<void> {
  const options = parseCliArgs(process.argv.slice(2));
  await ensureProjectDirs();
  await saveAuthState(options);
  process.stdout.write("登录态已保存到 storage/auth.json\n");
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`保存登录态失败：${message}\n`);
  process.exitCode = 1;
});

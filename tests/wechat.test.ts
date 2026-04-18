import test from "node:test";
import assert from "node:assert/strict";
import { closeContextSession, safeContent } from "../src/wechat.js";

test("safeContent 会在页面导航期间自动重试", async () => {
  const waitCalls: number[] = [];
  let contentCalls = 0;

  const result = await safeContent(
    {
      async content() {
        contentCalls += 1;
        if (contentCalls === 1) {
          throw new Error("Page.content: Unable to retrieve content because the page is navigating and changing the content.");
        }
        return "<html>ok</html>";
      },
      async waitForLoadState() {
        return undefined;
      },
      async waitForTimeout(timeout) {
        waitCalls.push(timeout);
      }
    },
    1_000,
    10
  );

  assert.equal(result, "<html>ok</html>");
  assert.equal(contentCalls, 2);
  assert.deepEqual(waitCalls, [10]);
});

test("closeContextSession 会依次关闭 context 和 browser", async () => {
  const calls: string[] = [];

  await closeContextSession({
    context: {
      async close() {
        calls.push("context");
      }
    } as never,
    browser: {
      async close() {
        calls.push("browser");
      }
    } as never
  });

  assert.deepEqual(calls, ["context", "browser"]);
});

test("closeContextSession 在 context.close 失败时仍会关闭 browser", async () => {
  const calls: string[] = [];

  await assert.rejects(
    closeContextSession({
      context: {
        async close() {
          calls.push("context");
          throw new Error("context close failed");
        }
      } as never,
      browser: {
        async close() {
          calls.push("browser");
        }
      } as never
    }),
    /context close failed/
  );

  assert.deepEqual(calls, ["context", "browser"]);
});

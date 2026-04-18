import { writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, type Browser, type BrowserContext, type Frame, type Page } from "playwright";
import { outputDir, storageDir, writeJson } from "./fs.js";
import { extractDeadlineByLabel, extractDeadlineFromJson, extractDeadlineFromText } from "./parser.js";
import type { CandidateHit, CliOptions, FetchResult, ResponseCapture } from "./types.js";

export const authStatePath = path.join(storageDir, "auth.json");

export type BrowserSession = {
  browser: Browser;
  context: BrowserContext;
};

export async function launchContext(options: CliOptions, requireAuthState: boolean): Promise<BrowserSession> {
  const browser = await chromium.launch({ headless: !options.headed });
  const context = await browser.newContext({
    storageState: requireAuthState ? authStatePath : undefined,
    viewport: { width: 1440, height: 1200 }
  });

  return { browser, context };
}

export async function closeContextSession(session: BrowserSession): Promise<void> {
  let contextError: unknown;

  try {
    await session.context.close();
  } catch (error) {
    contextError = error;
  }

  try {
    await session.browser.close();
  } catch (error) {
    if (contextError) {
      throw new AggregateError([contextError, error], "关闭浏览器会话时发生多个错误。");
    }
    throw error;
  }

  if (contextError) {
    throw contextError;
  }
}

export async function saveAuthState(options: CliOptions): Promise<void> {
  const session = await launchContext(options, false);
  try {
    const page = await session.context.newPage();
    await page.goto(options.url, { waitUntil: "domcontentloaded" });

    process.stdout.write(
      `浏览器已打开，请在 ${options.manualSeconds} 秒内完成登录。完成后回到终端按回车保存登录态。\n`
    );

    await waitForEnterOrTimeout(options.manualSeconds * 1000);
    await session.context.storageState({ path: authStatePath, indexedDB: true });
  } finally {
    await closeContextSession(session);
  }
}

function waitForEnterOrTimeout(timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      process.stdin.pause();
      resolve();
    }, timeoutMs);

    process.stdin.resume();
    process.stdin.setEncoding("utf8");
    process.stdin.once("data", () => {
      clearTimeout(timer);
      process.stdin.pause();
      resolve();
    });
  });
}

async function captureResponse(response: Awaited<ReturnType<Page["waitForResponse"]>>): Promise<ResponseCapture | null> {
  const contentType = response.headers()["content-type"] ?? "";
  const url = response.url();
  const status = response.status();

  if (!contentType.includes("json") && !contentType.includes("javascript") && !contentType.includes("text")) {
    return null;
  }

  try {
    const text = await response.text();
    const bodyPreview = text.slice(0, 3000);
    const matched = collectCandidatesFromUnknown(text);
    if (matched.length === 0) {
      return null;
    }

    return {
      url,
      status,
      contentType,
      matched,
      bodyPreview
    };
  } catch {
    return null;
  }
}

async function getBusinessFrame(page: Page): Promise<Frame | null> {
  const iframeLocator = page.locator("#js_iframe");
  await iframeLocator.waitFor({ timeout: 15_000 }).catch(() => undefined);
  const handle = await iframeLocator.elementHandle();
  if (!handle) {
    return null;
  }

  return handle.contentFrame();
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(fallback), timeoutMs);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(fallback);
      });
  });
}

type ContentReader = {
  content(): Promise<string>;
  waitForLoadState?(state?: "load" | "domcontentloaded" | "networkidle"): Promise<void>;
  waitForTimeout(timeout: number): Promise<void>;
};

export async function safeContent(reader: ContentReader, timeoutMs = 3_000, retryDelayMs = 200): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;

  if (reader.waitForLoadState) {
    await reader.waitForLoadState("domcontentloaded").catch(() => undefined);
  }

  while (Date.now() < deadline) {
    try {
      return await reader.content();
    } catch (error) {
      lastError = error;
      await reader.waitForTimeout(retryDelayMs);
    }
  }

  if (lastError) {
    throw lastError;
  }

  return reader.content();
}

async function extractDeadlineFromFrameDom(frame: Frame): Promise<CandidateHit[]> {
  const rawHits = await frame
    .evaluate(() => {
      const results: Array<{ path: string; value: string }> = [];
      const datePattern =
        /20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:[日\sT]*\d{1,2}:\d{2}(?::\d{2})?)?/;

      const elements = Array.from(document.querySelectorAll("body *"));
      for (const element of elements) {
        const text = (element.textContent || "").replace(/\s+/g, " ").trim();
        if (!text || !text.includes("处理截止时间")) {
          continue;
        }

        const siblingTexts = [
          text,
          (element.nextElementSibling?.textContent || "").replace(/\s+/g, " ").trim(),
          (element.parentElement?.textContent || "").replace(/\s+/g, " ").trim()
        ];

        for (const candidateText of siblingTexts) {
          const matched = candidateText.match(datePattern);
          if (matched?.[0]) {
            results.push({
              path: "$iframeDom.处理截止时间",
              value: matched[0]
            });
          }
        }
      }

      return results;
    })
    .catch(() => []);

  return rawHits.map((hit) => ({
    ...hit,
    source: "page-text" as const
  }));
}

async function openRefundDetail(frame: Frame): Promise<void> {
  const action = frame.getByText("处理", { exact: true }).last();
  const count = await frame.getByText("处理", { exact: true }).count().catch(() => 0);
  if (count === 0) {
    return;
  }

  await action.click({ timeout: 10_000 }).catch(() => undefined);
  await frame.waitForTimeout(3_000);
}

function collectCandidatesFromUnknown(value: string): CandidateHit[] {
  const textHits = extractDeadlineFromText(value);
  if (textHits.length > 0) {
    return textHits;
  }

  try {
    const parsed = JSON.parse(value);
    return extractDeadlineFromJson(parsed);
  } catch {
    return [];
  }
}

function candidatePriority(hit: CandidateHit): number {
  const path = hit.path.toLowerCase();

  if (path.includes("iframedom") && path.includes("处理截止时间")) {
    return 200;
  }

  if (path.includes("iframetext") && path.includes("处理截止时间")) {
    return 180;
  }

  if (path.includes("user_refund_check_list") && path.includes("appeal_deadline_time")) {
    return 100;
  }

  if (path.includes("user_refund_check_list") && path.includes("deadline_time")) {
    return 95;
  }

  if (path.includes("refund") && path.includes("deadline")) {
    return 90;
  }

  if (path.includes("federation_token") || path.includes("annual_verify_status")) {
    return -100;
  }

  if (hit.source === "page-text") {
    return 80;
  }

  return 10;
}

function normalizeCandidateValue(hit: CandidateHit): string {
  if (/^\d{10}$/.test(hit.value)) {
    const seconds = Number(hit.value);
    if (seconds >= 1_700_000_000 && seconds <= 1_900_000_000) {
      return new Date(seconds * 1000).toLocaleString("zh-CN", {
        hour12: false,
        timeZone: "Asia/Shanghai"
      });
    }
  }

  return hit.value;
}

function pickBestHit(textHits: CandidateHit[], responseHits: ResponseCapture[]): CandidateHit | undefined {
  const allHits: CandidateHit[] = [...textHits];

  for (const response of responseHits) {
    allHits.push(...response.matched);
  }

  if (allHits.length === 0) {
    return undefined;
  }

  return [...allHits].sort((left, right) => candidatePriority(right) - candidatePriority(left))[0];
}

function buildResultHit(hit: CandidateHit): CandidateHit {
  return {
    ...hit,
    value: normalizeCandidateValue(hit)
  };
}

export async function fetchDeadline(options: CliOptions): Promise<FetchResult> {
  const session = await launchContext(options, true);
  try {
    const page = await session.context.newPage();
    const captures: ResponseCapture[] = [];

    page.on("response", async (response) => {
      const capture = await captureResponse(response);
      if (capture) {
        captures.push(capture);
      }
    });

    await page.goto(options.url, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => undefined);

    if (options.keyword) {
      await page.getByText(options.keyword, { exact: false }).first().waitFor({ timeout: 5000 }).catch(() => undefined);
    }

    await page.waitForTimeout(options.responseTimeoutMs);

    const finalUrl = page.url();
    const html = await safeContent(page, 5_000).catch(() => "");
    const pageText = await page.locator("body").textContent().catch(() => "") ?? "";
    const outerTextHits = extractDeadlineFromText(pageText);
    const frame = await getBusinessFrame(page);
    let iframeHtml = "";
    let iframeText = "";
    let iframeHits: CandidateHit[] = [];

    if (frame) {
      await frame.waitForLoadState().catch(() => undefined);
      await page.waitForTimeout(3000);
      await openRefundDetail(frame);
      iframeHtml = await withTimeout(safeContent(frame, 10_000), 10_000, "");
      iframeText = (await withTimeout(frame.locator("body").textContent(), 10_000, "")) ?? "";
      iframeHits = [
        ...extractDeadlineFromFrameDom(frame),
        ...extractDeadlineByLabel(iframeText, "处理截止时间", "$iframeText.处理截止时间"),
        ...extractDeadlineFromText(iframeText).map((hit) => ({
          ...hit,
          path: "$iframeText"
        }))
      ];
    }

    const pickedHit = pickBestHit([...iframeHits, ...outerTextHits], captures);
    const bestHit = pickedHit ? buildResultHit(pickedHit) : undefined;

    await writeFile(path.join(outputDir, "page.html"), html, "utf8");
    await writeFile(path.join(outputDir, "page.txt"), pageText, "utf8");
    await writeFile(path.join(outputDir, "iframe.html"), iframeHtml, "utf8");
    await writeFile(path.join(outputDir, "iframe.txt"), iframeText, "utf8");
    await writeJson(path.join(outputDir, "responses.json"), captures);

    const isAuthError =
      pageText.includes("登录") ||
      pageText.includes("无权限") ||
      html.includes('"ret":200003') ||
      html.includes('"ret": 200003');

    const result: FetchResult = bestHit
      ? {
          ok: true,
          deadlineText: bestHit.value,
          deadlineSource: bestHit.source,
          matchedPath: bestHit.path,
          pageUrl: finalUrl,
          responseCount: captures.length,
          note: "已找到候选截止时间，请结合页面截图或后台记录复核。"
        }
      : {
          ok: false,
          pageUrl: finalUrl,
          responseCount: captures.length,
          note: isAuthError
            ? "未找到截止时间，且页面疑似处于未登录或无权限状态。"
            : "未找到截止时间，请改用 --headed 观察页面交互，或补充更具体的定位关键词。"
        };

    await writeJson(path.join(outputDir, "result.json"), result);
    return result;
  } finally {
    await closeContextSession(session);
  }
}

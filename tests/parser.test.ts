import test from "node:test";
import assert from "node:assert/strict";
import { extractDeadlineByLabel, extractDeadlineFromJson, extractDeadlineFromText } from "../src/parser.js";

test("可以从中文文本中提取截止时间", () => {
  const hits = extractDeadlineFromText("申请处理截止时间：2026-04-20 18:00，请尽快补充资料。");
  assert.equal(hits[0]?.value, "2026-04-20 18:00");
});

test("可以从 JSON 截止字段中提取截止时间", () => {
  const hits = extractDeadlineFromJson({
    data: {
      deadlineTime: "2026-04-21 23:59:59"
    }
  });

  assert.equal(hits[0]?.value, "2026-04-21 23:59:59");
  assert.equal(hits[0]?.path, "$.data.deadlineTime");
});

test("可以从嵌套文本值中提取截止时间", () => {
  const hits = extractDeadlineFromJson({
    list: [
      {
        title: "未成年人支付退款申请",
        desc: "处理截止时间：2026年04月22日 12:30"
      }
    ]
  });

  assert.equal(hits[0]?.value, "2026年04月22日 12:30");
});

test("可以按处理截止时间标签提取对应时间", () => {
  const hits = extractDeadlineByLabel("处理截止时间 2026-04-20 19:07:26 申诉截止时间 2026-04-21 10:19:34", "处理截止时间");
  assert.equal(hits[0]?.value, "2026-04-20 19:07:26");
});

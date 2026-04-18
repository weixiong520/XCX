import { DEADLINE_KEYWORDS } from "./constants.js";
import type { CandidateHit } from "./types.js";

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function createDeadlineRegexes(): RegExp[] {
  return [
    /(?:申请处理截止时间|处理截止时间|处理截止日期|截止时间|截止日期)[：:\s]*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}(?:[日\sT]*[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)/gi,
    /(?:deadline|due|expire(?:d)?(?:\s*time)?)[\s:=：-]*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}(?:[ T][0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)/gi
  ];
}

function createLabeledDeadlineRegex(label: string): RegExp {
  const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `${escapedLabel}[：:\\s]*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}(?:[日\\sT]*[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)`,
    "gi"
  );
}

export function extractDeadlineFromText(text: string): CandidateHit[] {
  const normalized = normalizeText(text);
  const hits: CandidateHit[] = [];

  for (const regex of createDeadlineRegexes()) {
    for (const match of normalized.matchAll(regex)) {
      const value = normalizeText(match[1] ?? "");
      if (value) {
        hits.push({
          path: "$pageText",
          value,
          source: "page-text"
        });
      }
    }
  }

  return dedupeHits(hits);
}

export function extractDeadlineByLabel(text: string, label: string, path = "$pageText"): CandidateHit[] {
  const normalized = normalizeText(text);
  const hits: CandidateHit[] = [];

  for (const match of normalized.matchAll(createLabeledDeadlineRegex(label))) {
    const value = normalizeText(match[1] ?? "");
    if (value) {
      hits.push({
        path,
        value,
        source: "page-text"
      });
    }
  }

  return dedupeHits(hits);
}

function dedupeHits(hits: CandidateHit[]): CandidateHit[] {
  const seen = new Set<string>();
  return hits.filter((hit) => {
    const key = `${hit.path}|${hit.value}|${hit.source}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function keyMatched(key: string): boolean {
  const lower = key.toLowerCase();
  return DEADLINE_KEYWORDS.some((keyword) => lower.includes(keyword.toLowerCase()));
}

function valueMaybeDeadline(value: string): boolean {
  const lower = value.toLowerCase();
  const hasKeyword = DEADLINE_KEYWORDS.some((keyword) => lower.includes(keyword.toLowerCase()));
  const hasDate = /20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}/.test(value) || /20\d{2}-\d{1,2}-\d{1,2}/.test(value);
  return hasKeyword || hasDate;
}

export function extractDeadlineFromJson(input: unknown, currentPath = "$"): CandidateHit[] {
  const hits: CandidateHit[] = [];

  if (input === null || input === undefined) {
    return hits;
  }

  if (typeof input === "string") {
    const normalized = normalizeText(input);
    if (valueMaybeDeadline(normalized)) {
      for (const textHit of extractDeadlineFromText(normalized)) {
        hits.push({
          path: currentPath,
          value: textHit.value,
          source: "json-value"
        });
      }
    }
    return dedupeHits(hits);
  }

  if (typeof input === "number" || typeof input === "boolean") {
    return hits;
  }

  if (Array.isArray(input)) {
    input.forEach((item, index) => {
      hits.push(...extractDeadlineFromJson(item, `${currentPath}[${index}]`));
    });
    return dedupeHits(hits);
  }

  for (const [key, value] of Object.entries(input)) {
    const nextPath = `${currentPath}.${key}`;
    if (keyMatched(key)) {
      const stringValue = typeof value === "string" ? normalizeText(value) : JSON.stringify(value);
      if (stringValue) {
        const directTextHits = extractDeadlineFromText(`${key}:${stringValue}`);
        if (directTextHits.length > 0) {
          hits.push(
            ...directTextHits.map((hit) => ({
              path: nextPath,
              value: hit.value,
              source: "json-key" as const
            }))
          );
        } else {
          hits.push({
            path: nextPath,
            value: stringValue,
            source: "json-key"
          });
        }
      }
    }
    hits.push(...extractDeadlineFromJson(value, nextPath));
  }

  return dedupeHits(hits);
}

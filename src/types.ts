export interface CliOptions {
  url: string;
  headed: boolean;
  keyword?: string;
  responseTimeoutMs: number;
  manualSeconds: number;
}

export interface CandidateHit {
  path: string;
  value: string;
  source: "json-key" | "json-value" | "page-text";
}

export interface ResponseCapture {
  url: string;
  status: number;
  contentType: string;
  matched: CandidateHit[];
  bodyPreview: string;
}

export interface FetchResult {
  ok: boolean;
  deadlineText?: string;
  deadlineSource?: string;
  matchedPath?: string;
  pageUrl: string;
  responseCount: number;
  note: string;
}

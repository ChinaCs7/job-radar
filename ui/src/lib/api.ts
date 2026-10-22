// 开发时界面跑在 Vite（5173），接口在 17860；打包后界面和接口同源
export const API_BASE = location.port === "5173" ? "http://127.0.0.1:17860" : "";

export type Region = "domestic" | "overseas";
export type JobStatus = "new" | "seen" | "starred" | "applied" | "dismissed";

export interface Job {
  id: string;
  serial: number;
  source: string;
  title: string;
  company: string;
  city: string;
  region: Region;
  remote: boolean;
  salary: string;
  salary_min_k: number | null;
  job_type: string;
  experience: string;
  education: string;
  tags: string[];
  description: string;
  url: string;
  platform: string;
  published_at: string;
  first_seen: string;
  last_seen: string;
  score: number | null;
  score_reason: string | null;
  ai_summary: string | null;
  status: JobStatus;
  title_zh: string | null;
  verdict: "" | "recommend" | "maybe" | "no" | null;
  verdict_reason: string | null;
  also: { source: string; platform: string; url: string; id: string }[];
}

export interface Run {
  id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  ok: number | null;
  found: number;
  added: number;
  error: string | null;
  error_kind: string | null;
}

export type SourceState = "ok" | "idle" | "running" | "queued" | "paused" | "error" | "disabled";

export interface SourceConfig {
  enabled: boolean;
  interval_min: number;
  night_pause: boolean;
  paused?: string;
  paused_reason?: string;
  [k: string]: unknown;
}

export interface Source {
  id: string;
  name: string;
  group: string;
  region: string;
  needs_login: boolean;
  needs_key: boolean;
  browser: boolean;
  note: string;
  config: SourceConfig;
  state: SourceState;
  last_run: Run | null;
  total: number;
  next_run: string | null;
  night_now: boolean;
}

export interface Criteria {
  keywords: string[];
  cities: string[];
  salary_min_k: number;
  job_types: string[];
  exclude: string[];
  regions: { domestic: boolean; overseas: boolean; remote: boolean };
  profile: string;
  max_age_days: number;
}

export interface Settings {
  onboarded: boolean;
  running: boolean;
  theme: "light" | "dark" | "system";
  criteria: Criteria;
  sources: Record<string, SourceConfig>;
  llm: { api_key: string; base_url: string; model: string; enrich: boolean; has_key: boolean; key_hint: string };
  night: { start: number; end: number };
}

export interface Stats {
  total: number;
  today: number;
  today_high: number;
  today_no: number;
  recommend_total: number;
  by_day: { day: string; n: number }[];
  by_source: Record<string, number>;
}

export interface Overview {
  stats: Stats;
  sources: Source[];
  running: boolean;
  has_key: boolean;
  onboarded: boolean;
  has_keywords: boolean;
  activity: { running: string[]; queued: string[]; pending_enrich: number };
}

export interface UsageRow {
  calls: number; prompt: number; hit: number; completion: number; requests: number; cost: number;
}
export interface Usage {
  today: UsageRow; month: UsageRow; total: UsageRow;
  by_day: (UsageRow & { day: string })[];
  by_kind: (UsageRow & { kind: string })[];
  recent: { id: number; at: string; kind: string; model: string; prompt_tokens: number; cache_hit_tokens: number;
    completion_tokens: number; requests: number; peak: number; cost: number }[];
  price: { input_hit: number; input_miss: number; output: number; search_per_1k: number; off_peak_ratio: number };
  peak_now: boolean;
}
export interface Proposal {
  proposal_id: string;
  changes: { field: string; label: string; before: string; after: string }[];
  enable_sources: string[];
  disable_sources: string[];
  reason: string;
}

export interface BrowserPlatform {
  id: string; name: string; group: string; enabled: boolean; state: SourceState; paused_reason: string;
  last_error: string; needs_login: boolean; verify_once: boolean; home: string;
}

export interface LogLine { id: number; at: string; level: string; source: string; message: string }

export class ApiError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(API_BASE + path, {
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError("连不上本地服务，请确认求职雷达正在运行");
  }
  if (!r.ok) {
    let msg = `请求失败（${r.status}）`;
    try { msg = (await r.json()).detail || msg; } catch { /* 不是 JSON */ }
    throw new ApiError(msg);
  }
  return r.json();
}

const body = (b: unknown) => ({ method: "POST", body: JSON.stringify(b) });

export const api = {
  overview: () => req<Overview>("/api/overview"),
  settings: () => req<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Settings> | Record<string, unknown>) =>
    req<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  sources: () => req<Source[]>("/api/sources"),
  runNow: (source?: string) => req<{ ok: boolean; started: string[] }>("/api/run", body({ source })),
  setRunning: (running: boolean) => req<Settings>("/api/running", body({ running })),
  resume: (sid: string) => req(`/api/sources/${sid}/resume`, body({})),
  jobs: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "" && v !== false) qs.set(k, String(v));
    return req<{ jobs: Job[]; count: number }>(`/api/jobs?${qs}`);
  },
  jobBySerial: (n: number) => req<Job>(`/api/jobs/serial/${n}`),
  setStatus: (id: string, status: JobStatus) =>
    req<Job>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  stats: () => req<Stats>("/api/stats"),
  runs: () => req<Run[]>("/api/runs?limit=200"),
  logs: () => req<LogLine[]>("/api/logs?limit=300"),
  usage: () => req<Usage>("/api/usage?days=30"),
  browserPlatforms: () => req<BrowserPlatform[]>("/api/browser/platforms"),
  openLink: (url: string) => req<{ ok: boolean }>("/api/open", body({ url })),
  browserStatus: () => req<{ running: boolean; browser: string | null }>("/api/browser/status"),
  openBrowser: (platform?: string, url?: string) => req("/api/browser/open", body({ platform, url })),
  checkLogin: (platform: string) => req<{ state: string; message: string }>(`/api/login/${platform}/check`, body({})),
  testLlm: (cfg: Record<string, string>) => req<{ ok: boolean; message: string }>("/api/llm/test", body(cfg)),
  assistant: (messages: { role: string; content: string }[]) =>
    req<{ reply: string; steps: { tool: string; args: Record<string, unknown>; count: number | null }[]; proposals?: Proposal[] }>(
      "/api/assistant", body({ messages })),
  uploadAttachment: async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    let r: Response;
    try { r = await fetch(API_BASE + "/api/assistant/upload", { method: "POST", body: fd }); }
    catch { throw new ApiError("连不上本地服务"); }
    if (!r.ok) { let m = `上传失败（${r.status}）`; try { m = (await r.json()).detail || m; } catch { /* */ } throw new ApiError(m); }
    return r.json() as Promise<{ name: string; text: string; chars: number; masked: number }>;
  },
  applyProposal: (pid: string) => req<{ ok: boolean }>(`/api/assistant/proposals/${pid}/apply`, body({})),
  discardProposal: (pid: string) => req<{ ok: boolean }>(`/api/assistant/proposals/${pid}/discard`, body({})),
  summary: (date: string) => req<{ text?: string; count?: number; at?: string }>(`/api/summary?date=${date}`),
  makeSummary: (date: string) => req<{ text: string; count: number; at: string }>("/api/summary", body({ date })),
  exportHtml: (days: number) => req<{ path: string; name: string; count: number }>(`/api/export?days=${days}`),
};

// Electron 预加载脚本暴露的能力；在普通浏览器里不存在，退回到 window.open
interface DesktopBridge {
  openExternal(url: string): void;
  openReport(): void;
  showItem(path: string): void;
}
declare global { interface Window { desktop?: DesktopBridge; __SNAPSHOT__?: { jobs: Job[]; at: string; days: number } } }

export function openExternal(url: string) {
  if (window.desktop) window.desktop.openExternal(url);
  else window.open(url, "_blank", "noopener");
}

export function openReport() {
  if (window.desktop) window.desktop.openReport();
  else window.open(`${API_BASE || location.origin}/report`, "_blank", "noopener");
}

// 화면에 보이는 문구와 숫자 모양. 백엔드는 코드 값만 보내고, 문구는 여기서 정한다.

import type { AudioRate, Item, Plan, Resolution, Settings, Status, VideoRate } from "./api";

export const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: "1080p", label: "1080p (FHD)" },
  { value: "720p", label: "720p (HD)" },
  { value: "none", label: "제한 없음" },
];
export const VIDEO_RATES: VideoRate[] = ["5.0", "4.0", "3.5", "2.5", "1.5"];
export const AUDIO_RATES: AudioRate[] = ["192k", "128k", "96k"];

export const resolutionLabel = (r: Resolution) => RESOLUTIONS.find((x) => x.value === r)?.label ?? r;

export function fmtBytes(n: number): string {
  if (!n) return "-";
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** 초 → 1:02:03 또는 2:03. 모르면 "-". */
export function fmtDuration(sec: number): string {
  if (!sec || sec < 0) return "-";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** ffmpeg time=00:01:02.34 → 1:02 */
export function fmtClock(t: string): string {
  const m = /^(\d+):(\d+):(\d+)/.exec(t);
  return m ? fmtDuration(Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])) : "-";
}

export function fmtRate(bps: number): string {
  return bps ? `${(bps / 1_000_000).toFixed(1)} Mbps` : "-";
}

/** 파일이 있는 폴더(전체 경로에서 파일 이름을 뺀 것) */
export function folderOf(path: string): string {
  const i = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return i > 0 ? path.slice(0, i) : path;
}

export const PLAN_LABEL: Record<Exclude<Plan, null>, { label: string; hint: string }> = {
  scale: { label: "줄여서 변환", hint: "해상도 제한보다 커서 비율을 지켜 줄이고 다시 인코딩합니다" },
  encode: { label: "변환", hint: "최대 비트레이트에 맞춰 다시 인코딩합니다" },
  copy: { label: "복사", hint: "비트레이트가 4 Mbps 이하라 다시 인코딩하지 않고 mp4로 옮겨 담습니다" },
};

export const STARTABLE: Status[] = ["waiting", "stopped", "failed"];
export const isStartable = (i: Item) => STARTABLE.includes(i.status);

/** 상태 배지: 문구, 색(tone), 배지 밑에 적을 사유 */
export function describeStatus(i: Item): { label: string; tone: string; reason?: string } {
  switch (i.status) {
    case "analyzing": return { label: "분석 중", tone: "busy" };
    case "waiting": return { label: "대기", tone: "waiting" };
    case "converting": return { label: `변환 중 ${Math.round(i.percent * 100)}%`, tone: "converting" };
    case "done": return { label: "완료", tone: "ok", reason: i.source_deleted ? "원본 삭제함" : undefined };
    case "copied": return { label: "복사함", tone: "ok", reason: i.source_deleted ? "원본 삭제함" : undefined };
    case "failed": return { label: "실패", tone: "err", reason: i.message ?? undefined };
    case "stopped": return { label: "중단", tone: "stopped" };
  }
}

export const FILTERS = ["전체", "대기", "진행", "완료", "실패"] as const;
export type Filter = (typeof FILTERS)[number];

export function bucketOf(i: Item): Filter {
  if (i.status === "converting") return "진행";
  if (i.status === "done" || i.status === "copied") return "완료";
  if (i.status === "failed") return "실패";
  return "대기";
}

export function countBuckets(items: Item[]): Record<Filter, number> {
  const c: Record<Filter, number> = { 전체: items.length, 대기: 0, 진행: 0, 완료: 0, 실패: 0 };
  for (const i of items) c[bucketOf(i)] += 1;
  return c;
}

export function describeSummary(items: Item[]): string {
  if (!items.length) return "비어 있음";
  const c = countBuckets(items);
  const parts = [`${items.length}개`];
  if (c.대기) parts.push(`대기 ${c.대기}`);
  if (c.완료) parts.push(`완료 ${c.완료}`);
  if (c.실패) parts.push(`실패 ${c.실패}`);
  return parts.join(" · ");
}

/** 저장될 이름의 예: movie.mkv → movie_cuda.mp4 */
export function exampleName(s: Settings): string {
  return `movie.mkv → movie${s.name_mode === "suffix" ? s.suffix : ""}.mp4`;
}

/** 변환을 시작하기 전에 받아야 할 확인. 없으면 빈 배열. n 은 변환할 항목 수. */
export function startWarnings(s: Settings, n: number): string[] {
  const out: string[] = [];
  if (s.delete_source) {
    out.push(`변환에 성공한 원본 최대 ${n}개를 영구 삭제합니다. 휴지통으로 가지 않습니다.`);
  }
  if (s.name_mode === "overwrite") {
    out.push(s.save_mode === "same"
      ? "원본과 같은 폴더에 같은 이름(.mp4)으로 저장합니다.\n원본이 mp4이거나 같은 이름의 mp4가 있으면 그 파일이 바뀝니다."
      : "저장 폴더에 같은 이름의 파일이 있으면 그 파일이 바뀝니다.");
  }
  return out;
}

/** 이미 떠 있는 알림에 새 알림을 덧붙인다(같은 문구는 한 번만). */
export function mergeMessages(existing: string, next: string): string {
  const a = existing.trim();
  const b = next.trim();
  if (!a) return b;
  if (!b || a.includes(b)) return a;
  return `${a}\n\n${"-".repeat(20)}\n\n${b}`;
}

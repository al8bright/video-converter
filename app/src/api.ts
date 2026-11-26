// 백엔드 클라이언트: 연결은 공통 파일 `backend.ts` 가 맡고, 여기서는 이벤트와 응답 형태를 둔다.

import { socket } from "./backend";

export { ApiError, api, connect, inTauri } from "./backend";

/** 상태 변경을 받는다. 끊기면 1초 뒤 다시 붙는다. 돌려준 함수로 닫는다. */
export function events(handlers: { state: (s: AppData) => void; link: (up: boolean) => void }): () => void {
  return socket("/events", (data) => {
    const e = data as { type: string };
    if (e.type === "state") handlers.state(e as unknown as AppData);
  }, handlers.link);
}

// ---------------------------------------------------------------------- 형태 (core/service.py, config.py)

export type Status = "analyzing" | "waiting" | "converting" | "done" | "copied" | "failed" | "stopped";
/** 지금 설정으로 변환하면: 줄여서 변환 | 변환 | mp4로 복사. 영상 정보를 못 읽었으면 null */
export type Plan = "scale" | "encode" | "copy" | null;
export type VideoRate = "5.0" | "4.0" | "3.5" | "2.5" | "1.5";
export type AudioRate = "192k" | "128k" | "96k";
export type Resolution = "1080p" | "720p" | "none";

export interface Item {
  id: string;
  path: string;
  name: string;
  size: number;
  width: number;
  height: number;
  duration: number;
  bit_rate: number;
  status: Status;
  message: string | null;
  source_deleted: boolean;
  output: string | null;
  percent: number;
  time: string;
  speed: string;
  plan: Plan;
}

export interface BatchResult {
  message: string;
  all_ok: boolean;
  done: number;
  copied: number;
  deleted: number;
  failed: number;
  stopped: number;
  total: number;
}

export interface Batch {
  running: boolean;
  stop_requested: boolean;
  total: number;
  finished: number;
  jobs: number;
  started_at: number | null;
  result: BatchResult | null;
  added_during: number;
  overall: number;
}

export interface Settings {
  jobs: number | null; // null 이면 권장값
  video_rate: VideoRate;
  audio_rate: AudioRate;
  resolution: Resolution;
  delete_source: boolean;
  save_mode: "same" | "folder";
  save_dir: string;
  name_mode: "suffix" | "overwrite";
  suffix: string;
  sidebar: "open" | "closed";
}

export interface Notice {
  id: number;
  text: string;
  tone: "info" | "warn";
}

export interface AppData {
  version: number;
  items: Item[];
  batch: Batch;
  settings: Settings;
  notices: Notice[];
}

export interface SystemInfo {
  version: string;
  ffmpeg: string | null;
  ffprobe: string | null;
  extensions: string[];
  max_jobs: number;
  gpu: string | null;
  vram_mb: number;
  ram_gb: number;
  recommended_jobs: number;
}

/** 응답에 사용자에게 보여 줄 안내가 실려 오는 동작들 */
export interface WithMessage {
  message?: string | null;
}

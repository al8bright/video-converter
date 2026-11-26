import { useState } from "react";
import { api, inTauri, type Settings } from "./api";
import { useApp } from "./ctx";
import { AUDIO_RATES, exampleName, RESOLUTIONS, VIDEO_RATES } from "./format";
import { ICONS } from "./icons";
import { Check, eyebrow, Icon, Note, Page, Seg } from "./ui";

export function SettingsScreen() {
  const { data, system, act } = useApp();
  const s = data.settings;
  const locked = data.batch.running;
  const put = (patch: Partial<Settings>) => act(() => api.put("/settings", patch));

  const [dirDraft, setDirDraft] = useState<string | null>(null);
  const [suffixDraft, setSuffixDraft] = useState<string | null>(null);
  const dir = dirDraft ?? s.save_dir;
  const suffix = suffixDraft ?? s.suffix;
  const commitDir = async (value: string) => {
    if (value.trim() && value !== s.save_dir) await put({ save_dir: value });
    setDirDraft(null);
  };
  const commitSuffix = async () => {
    if (suffix !== s.suffix) await put({ suffix });
    setSuffixDraft(null);
  };
  const browse = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const picked = await open({ directory: true, defaultPath: s.save_dir || undefined, title: "저장 폴더 고르기" });
    if (typeof picked === "string") {
      await commitDir(picked);
      if (s.save_mode !== "folder") await put({ save_mode: "folder" });
    }
  };

  const recommended = system?.recommended_jobs;
  const jobOptions = [
    { value: 0, label: recommended ? `권장 ${recommended}` : "권장" },
    ...Array.from({ length: system?.max_jobs ?? 8 }, (_, i) => ({ value: i + 1, label: String(i + 1) })),
  ];

  return (
    <Page title="설정" eyebrow={eyebrow("SETTINGS", locked ? "변환하는 동안 잠김" : "바꾸면 바로 저장됩니다")}>
      {locked && <Note tone="warn">변환하는 동안은 설정을 바꿀 수 없습니다. 끝나거나 중단한 뒤 바꿔 주세요.</Note>}

      <section className="card" aria-label="화질">
        <h2>화질</h2>
        <div className="setting">
          해상도 제한
          <Seg label="해상도 제한" value={s.resolution} disabled={locked} options={RESOLUTIONS}
            onChange={(v) => put({ resolution: v })} />
          <span className="hint">이보다 큰 영상만 비율을 지켜 줄입니다. 작은 영상은 키우지 않습니다.</span>
        </div>
        <div className="setting">
          최대 비디오 비트레이트
          <Seg label="최대 비디오 비트레이트" value={s.video_rate} disabled={locked}
            options={VIDEO_RATES.map((v) => ({ value: v, label: `${v} Mbps` }))} onChange={(v) => put({ video_rate: v })} />
          <span className="hint">낮출수록 파일이 작아지지만, 움직임이 많은 장면이 뭉개질 수 있습니다. 3.5 Mbps를 권장합니다.</span>
        </div>
        <div className="setting">
          오디오 비트레이트 (AAC)
          <Seg label="오디오 비트레이트" value={s.audio_rate} disabled={locked}
            options={AUDIO_RATES.map((v) => ({ value: v, label: v }))} onChange={(v) => put({ audio_rate: v })} />
        </div>
      </section>

      <section className="card" aria-label="동시 변환">
        <h2>동시 변환</h2>
        <div className="setting">
          한 번에 변환할 파일 수
          <Seg label="동시 변환 작업 수" value={s.jobs ?? 0} disabled={locked} options={jobOptions}
            onChange={(v) => put({ jobs: v === 0 ? null : v })} />
          <span className="hint">
            권장값은 GPU 메모리로 정합니다(4GB 이하 1 · 8GB 이하 2 · 12GB 이하 3 · 그 이상 4). 메모리보다 많이 돌리면 인코더 오류가 날 수 있습니다.
            그래픽카드 발열이 걱정되면 1~2로 낮추세요.
          </span>
        </div>
      </section>

      <section className="card" aria-label="저장">
        <h2>저장</h2>
        <div className="setting">
          저장 위치
          <Seg label="저장 위치" value={s.save_mode} disabled={locked}
            options={[{ value: "same", label: "원본과 같은 폴더" }, { value: "folder", label: "지정 폴더" }]}
            onChange={(v) => put({ save_mode: v })} />
          <div className="path-row">
            <input className="field path" value={dir} disabled={locked || s.save_mode !== "folder"} aria-label="저장 폴더"
              spellCheck={false} placeholder="저장할 폴더 경로" onChange={(e) => setDirDraft(e.target.value)}
              onBlur={() => commitDir(dir)} onKeyDown={(e) => e.key === "Enter" && commitDir(dir)} />
            {inTauri && <button className="btn" disabled={locked} onClick={browse}>변경</button>}
            <button className="btn cyan-ghost" disabled={s.save_mode !== "folder" || !s.save_dir}
              onClick={() => act(() => api.post("/open/folder", {}))}><Icon d={ICONS.open} size={13} /> 열기</button>
          </div>
        </div>
        <div className="setting">
          파일 이름
          <Seg label="파일 이름" value={s.name_mode} disabled={locked}
            options={[{ value: "suffix", label: "접미사 붙이기" }, { value: "overwrite", label: "같은 이름 (덮어쓰기)" }]}
            onChange={(v) => put({ name_mode: v })} />
          {s.name_mode === "suffix" && (
            <input className="field suffix" value={suffix} disabled={locked} aria-label="접미사" spellCheck={false}
              onChange={(e) => setSuffixDraft(e.target.value)} onBlur={commitSuffix}
              onKeyDown={(e) => e.key === "Enter" && commitSuffix()} />
          )}
          <span className="hint mono">{exampleName(s)} · 결과는 항상 mp4입니다</span>
          {s.name_mode === "overwrite" && (
            <Note tone="warn">
              {s.save_mode === "same"
                ? "원본이 mp4면 변환한 파일로 바뀝니다. 다른 형식이면 같은 폴더에 같은 이름의 mp4가 생깁니다."
                : "저장 폴더에 같은 이름의 파일이 있으면 바뀝니다."}
            </Note>
          )}
        </div>
        <div className="setting">
          <label className="check-label">
            <Check checked={s.delete_source} disabled={locked} label="변환에 성공하면 원본 삭제"
              onChange={(v) => put({ delete_source: v })} />
            변환에 성공하면 원본 삭제
          </label>
          {s.delete_source && (
            <Note tone="warn">결과 파일을 확인한 뒤에만 지우지만, 휴지통으로 가지 않고 바로 지워집니다. 변환을 시작할 때 한 번 더 묻습니다.</Note>
          )}
        </div>
      </section>
    </Page>
  );
}

import { useEffect, useRef, useState } from "react";
import { api, type Batch, inTauri, type Item } from "./api";
import { useApp } from "./ctx";
import {
  countBuckets, describeStatus, describeSummary, exampleName, FILTERS, type Filter, bucketOf, fmtBytes, fmtClock,
  fmtDuration, folderOf, isStartable, PLAN_LABEL, resolutionLabel, startWarnings,
} from "./format";
import { ICONS } from "./icons";
import { Bar, Check, Chip, Ellipsis, Empty, eyebrow, Icon, Modal, Screen } from "./ui";

/** 상태 → 배지 색. 진행 중은 주 네온, 완료·실패는 상태색, 대기·중단은 무채색. */
const BADGE: Record<string, string> = {
  waiting: "badge", stopped: "badge", busy: "badge run", converting: "badge p", ok: "badge ok", err: "badge err",
};

export function QueueScreen() {
  const { data, act } = useApp();
  const { items, batch: b, settings } = data;
  const running = b.running;

  // 고른 항목. 새로 담긴 것은 처음부터 골라 둔다
  const [sel, setSel] = useState<Set<string>>(new Set());
  const known = useRef<Set<string>>(new Set());
  useEffect(() => {
    const ids = new Set(items.map((i) => i.id));
    const fresh = items.filter((i) => !known.current.has(i.id)).map((i) => i.id);
    known.current = ids;
    setSel((cur) => new Set([...[...cur].filter((id) => ids.has(id)), ...fresh]));
  }, [items]);

  const [bucket, setBucket] = useState<Filter>("전체");
  const [pathOpen, setPathOpen] = useState(false);
  const [path, setPath] = useState("");
  // 확인이 필요한 시작(원본 삭제·덮어쓰기): 무엇을 시작할지와 띄울 문구
  const [confirm, setConfirm] = useState<{ ids: string[] | null; lines: string[] } | null>(null);

  const startable = items.filter(isStartable);
  const picked = startable.filter((i) => sel.has(i.id));
  const counts = countBuckets(items);
  const shown = items.map((item, idx) => ({ item, idx })).filter(({ item }) => bucket === "전체" || bucketOf(item) === bucket);

  const toggleAll = (on: boolean) => setSel(on ? new Set(startable.map((i) => i.id)) : new Set());
  const toggle = (id: string, on: boolean) => setSel((cur) => {
    const next = new Set(cur);
    if (on) next.add(id);
    else next.delete(id);
    return next;
  });

  const run = (ids: string[] | null) => act(() => api.post("/batch/start", ids ? { ids } : {}));
  const start = (ids: string[] | null) => {
    const lines = startWarnings(settings, ids ? ids.length : startable.length);
    if (lines.length) setConfirm({ ids, lines });
    else void run(ids);
  };

  const addPaths = (paths: string[]) => paths.length ? act(() => api.post("/queue/paths", { paths })) : Promise.resolve(undefined);
  const pickFiles = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const exts = ["mkv", "avi", "mov", "wmv", "mp4", "m4v", "ts"];
    const r = await open({ multiple: true, title: "영상 파일 고르기", filters: [{ name: "영상", extensions: exts }] });
    if (r) await addPaths(Array.isArray(r) ? r : [r]);
  };
  const pickFolder = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const r = await open({ directory: true, multiple: true, title: "영상 폴더 고르기 (하위 폴더까지 찾습니다)" });
    if (r) await addPaths(Array.isArray(r) ? r : [r]);
  };
  const addTyped = async () => {
    // 탐색기의 '경로로 복사'는 따옴표를 붙인다. 여러 줄이면 줄마다 하나
    const paths = path.split(/\r?\n/).map((p) => p.trim().replace(/^"(.*)"$/, "$1")).filter(Boolean);
    if (await addPaths(paths)) setPath("");
  };

  return (
    <Screen title="대기열" eyebrow={eyebrow("QUEUE", `${describeSummary(items)}${running ? " · 변환 중" : ""}`)}
      bar={running ? <>
        <span className="spacer" />
        <span className="bar-hint">중단하면 변환 중인 파일은 지우고, 시작하지 않은 파일은 대기로 남깁니다</span>
        <button className="btn lg danger" disabled={b.stop_requested} onClick={() => act(() => api.post("/batch/stop"))}>
          {b.stop_requested ? "중단하는 중…" : "변환 중단"}
        </button>
      </> : <>
        <button className="btn bare" onClick={() => act(() => api.post("/queue/clear-finished"))}>완료 항목 정리</button>
        <button className="btn bare danger" disabled={!items.length} onClick={() => act(() => api.post("/queue/clear"))}>대기열 비우기</button>
        <span className="spacer" />
        <button className="btn lg" disabled={!picked.length} onClick={() => start(picked.map((i) => i.id))}>
          {picked.length ? `선택한 ${picked.length}개 변환` : "선택한 영상 변환"}
        </button>
        <button className="btn primary lg" disabled={!startable.length} onClick={() => { toggleAll(true); start(null); }}>
          변환 시작
        </button>
      </>}>
      <div className="queue-top">
        {(running || b.result) && <NowCard b={b} items={items} />}
        <HowCard locked={running} />
      </div>

      <div className="queue-tools">
        <Check checked={!!startable.length && picked.length === startable.length}
          indeterminate={!!picked.length && picked.length < startable.length}
          disabled={running || !startable.length} label="변환할 수 있는 영상 모두 고르기" onChange={toggleAll} />
        <span className="sel">{startable.length ? `${picked.length}개 선택` : ""}</span>
        <span className="grow" />
        {FILTERS.map((f) => (
          <Chip key={f} active={bucket === f} onClick={() => setBucket(f)}>{f} <span className="n">{counts[f]}</span></Chip>
        ))}
        {inTauri && <>
          <button className="btn sm cyan" onClick={pickFiles}><Icon d={ICONS.file} size={13} /> 파일 추가</button>
          <button className="btn sm cyan" onClick={pickFolder}><Icon d={ICONS.folder} size={13} /> 폴더 추가</button>
        </>}
        <button className={`btn sm ${inTauri ? "cyan-ghost" : "cyan"}`} aria-expanded={pathOpen} onClick={() => setPathOpen((v) => !v)}>
          <Icon d={ICONS.path} size={13} /> 경로로 추가
        </button>
      </div>
      {pathOpen && (
        <form className="link-row" onSubmit={(e) => { e.preventDefault(); void addTyped(); }}>
          <input className="field path" autoFocus value={path} onChange={(e) => setPath(e.target.value)} spellCheck={false}
            placeholder="D:\Videos 또는 D:\Videos\movie.mkv" aria-label="파일 또는 폴더 경로" />
          <button className="btn cyan" type="submit">대기열에 추가</button>
          <button className="btn" type="button" onClick={() => setPathOpen(false)}>닫기</button>
        </form>
      )}

      <div className="cols q-cols col-head" aria-hidden>
        <span /><span>#</span><span>파일</span><span>해상도</span><span>길이</span><span>크기</span><span>할 일</span><span>상태</span><span />
      </div>
      <div className="list" role="list" aria-label="대기열">
        {shown.length ? shown.map(({ item, idx }) => (
          <QueueRow key={item.id} item={item} num={idx + 1} locked={running}
            checked={sel.has(item.id)} onCheck={(on) => toggle(item.id, on)} />
        )) : <Empty>{items.length ? "이 분류에 해당하는 영상이 없습니다."
          : inTauri ? "변환할 영상 파일이나 폴더를 이 창에 끌어다 놓거나, '파일 추가'·'폴더 추가'로 넣어 주세요."
          : "'경로로 추가'에 영상 파일이나 폴더 경로를 넣어 주세요. 폴더는 하위 폴더까지 찾습니다."}</Empty>}
      </div>

      {confirm && (
        <Modal title="변환 전에 확인" onClose={() => setConfirm(null)}
          actions={<>
            <button className="btn" data-autofocus onClick={() => setConfirm(null)}>취소</button>
            <button className="btn danger-solid" onClick={() => { void run(confirm.ids); setConfirm(null); }}>변환 시작</button>
          </>}>
          {confirm.lines.join("\n\n")}
        </Modal>
      )}
    </Screen>
  );
}

function QueueRow({ item, num, locked, checked, onCheck }: {
  item: Item; num: number; locked: boolean; checked: boolean; onCheck: (on: boolean) => void;
}) {
  const { act } = useApp();
  const s = describeStatus(item);
  const can = isStartable(item);
  const finished = item.status === "done" || item.status === "copied";
  const plan = item.plan ? PLAN_LABEL[item.plan] : null;
  return (
    <div role="listitem" className={`row cols q-cols q-row${item.status === "converting" ? " current" : ""}${finished ? " finished" : ""}`}>
      <Check checked={can && checked} disabled={!can || locked} label={item.name} onChange={onCheck} />
      <span className="num">{num}</span>
      <span className="cell">
        <Ellipsis className="title" title={item.name}>{item.name}</Ellipsis>
        {/* 끝난 항목은 결과 파일 이름을 보인다. 폴더까지 적으면 앞부분만 보이고 이름이 잘린다 */}
        <Ellipsis className="sub" title={item.output ?? item.path}>
          {finished && item.output ? `→ ${item.output.slice(folderOf(item.output).length + 1)}` : folderOf(item.path)}
        </Ellipsis>
      </span>
      <span className="mono-cell">{item.width ? `${item.width}×${item.height}` : "-"}</span>
      <span className="mono-cell">{fmtDuration(item.duration)}</span>
      <span className="mono-cell">{fmtBytes(item.size)}</span>
      <span className="plan" title={plan?.hint}>{plan?.label ?? "-"}</span>
      <span className="status">
        <span className={BADGE[s.tone] ?? "badge"}>{s.label}</span>
        {s.reason && <span className="reason">{s.reason}</span>}
      </span>
      <span className="acts">
        {finished && (
          <button className="btn icon" aria-label={`${item.name} 결과 파일 폴더 열기`} title="결과 폴더 열기"
            onClick={() => act(() => api.post("/open/folder", { id: item.id }))}>
            <Icon d={ICONS.open} size={14} />
          </button>
        )}
        <button className="btn icon" disabled={locked} aria-label={`${item.name} 대기열에서 빼기`} title="대기열에서 빼기"
          onClick={() => act(() => api.del(`/queue/${item.id}`))}>
          <Icon d={ICONS.x} size={14} />
        </button>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------- 변환 방법 요약

function HowCard({ locked }: { locked: boolean }) {
  const { data, system, go } = useApp();
  const s = data.settings;
  const jobs = s.jobs ?? system?.recommended_jobs;
  return (
    <section className="card how" aria-label="변환 방법">
      <div className="card-head">
        <h2>변환 방법</h2>
        {locked
          ? <span className="badge"><Icon d={ICONS.lock} size={11} /> 변환하는 동안 잠김</span>
          : <button className="btn sm cyan-ghost" onClick={() => go("settings")}>설정 바꾸기</button>}
      </div>
      <dl className="how-list">
        <dt>화질</dt>
        <dd>{resolutionLabel(s.resolution)} 이하 · 최대 {s.video_rate} Mbps · AAC {s.audio_rate}</dd>
        <dt>동시</dt>
        <dd>{jobs ? `${jobs}개` : "-"}{s.jobs === null ? " (권장)" : ""}</dd>
        <dt>저장</dt>
        <dd>
          <Ellipsis title={s.save_mode === "folder" ? s.save_dir : undefined}>
            {s.save_mode === "same" ? "원본과 같은 폴더" : s.save_dir || "(폴더를 지정해 주세요)"}
          </Ellipsis>
          <span className="mono">{exampleName(s)}</span>
        </dd>
        {s.delete_source && <><dt>원본</dt><dd className="warn">변환에 성공하면 삭제</dd></>}
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------------- 지금 변환 중

function NowCard({ b, items }: { b: Batch; items: Item[] }) {
  if (!b.running && b.result) {
    const r = b.result;
    const tone = r.all_ok ? "badge ok" : r.failed ? "badge err" : "badge";
    const parts = [r.done && `변환 ${r.done}`, r.copied && `복사 ${r.copied}`, r.deleted && `원본 삭제 ${r.deleted}`].filter(Boolean);
    return (
      <section className="card now done" aria-label="지난 변환 결과">
        <div className="card-head">
          <span className="eyebrow"><span className="tracked">LAST RUN</span></span>
          <span className={tone}>{r.all_ok ? "모두 완료" : r.failed ? `실패 ${r.failed}` : "일부만 완료"}</span>
        </div>
        <h2>{r.message}</h2>
        {parts.length > 0 && <div className="detail">{parts.join(" · ")}</div>}
        {r.failed > 0 && <div className="detail">실패한 파일은 목록의 사유를 확인하고 '변환 시작'으로 다시 변환할 수 있습니다.</div>}
        <div className="overall">
          <span>전체</span>
          <Bar value={r.total ? (r.done + r.copied) / r.total : 0} tone="s" label="지난 변환 전체 진행률" />
          <span className="mono">{r.done + r.copied} / {r.total}개</span>
        </div>
      </section>
    );
  }

  const active = items.filter((i) => i.status === "converting");
  return (
    <section className="card now" aria-label="지금 변환 중" aria-live="polite">
      <div className="now-top">
        <div className="who">
          <span className="eyebrow"><span className="tracked">NOW</span> · 동시 {b.jobs}개 · {b.finished} / {b.total}개 끝남</span>
          <h2 className={b.stop_requested ? "danger" : undefined}>
            {b.stop_requested ? "중단하는 중…" : active.length ? `${active.length}개 변환 중` : "변환할 준비 중…"}
          </h2>
        </div>
        <div className="big-pct"><b>{Math.round(b.overall * 100)}%</b><span>전체</span></div>
      </div>
      <ol className="jobs">
        {active.map((i) => (
          <li key={i.id}>
            <div className="job-top">
              <Ellipsis className="title" title={i.name}>{i.name}</Ellipsis>
              <span className="job-pct">{Math.round(i.percent * 100)}%</span>
            </div>
            <Bar value={i.percent} tone="p" big label={`${i.name} 진행률`} />
            <span className="step-detail">
              {i.plan ? PLAN_LABEL[i.plan].label : "변환"} · {i.time ? `${fmtClock(i.time)} / ${fmtDuration(i.duration)}` : "시작하는 중"}
              {i.speed && i.speed !== "?" ? ` · ${i.speed}` : ""}
            </span>
          </li>
        ))}
      </ol>
      <div className="overall">
        <span>전체</span>
        <Bar value={b.overall} tone="s" label="전체 진행률" />
        <span className="mono">{Math.round(b.overall * 100)}%</span>
      </div>
    </section>
  );
}

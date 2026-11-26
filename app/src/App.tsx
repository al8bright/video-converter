import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type AppData, api, connect, events, inTauri, type SystemInfo, type WithMessage } from "./api";
import { type AppCtx, Ctx, type ScreenName, useApp } from "./ctx";
import { mergeMessages } from "./format";
import { HelpScreen } from "./Help";
import { ICONS } from "./icons";
import { QueueScreen } from "./Queue";
import { SettingsScreen } from "./Settings";
import { Bar, Ellipsis, Icon, Logo, Modal } from "./ui";

const VERSION = "1.0.0";

export default function App() {
  const [ready, setReady] = useState<"wait" | "ok" | string>("wait");
  const [data, setData] = useState<AppData | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [screen, setScreen] = useState<ScreenName>("queue");
  const [linkUp, setLinkUp] = useState(true);
  const [alertText, setAlertText] = useState("");
  const [askClose, setAskClose] = useState(false);
  const seenNotice = useRef<number | null>(null);
  const running = !!data?.batch.running;
  const runningRef = useRef(false);
  useEffect(() => {
    runningRef.current = running;
  }, [running]);

  const alert = useCallback((text: string) => setAlertText((cur) => mergeMessages(cur, text)), []);
  const act = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    try {
      const r = await fn();
      const m = (r as WithMessage | null)?.message;
      if (m) alert(m);
      return r;
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
      return undefined;
    }
  }, [alert]);

  useEffect(() => {
    let stop: (() => void) | undefined;
    connect()
      .then(async () => {
        setData(await api.get<AppData>("/state"));
        setReady("ok");
        stop = events({ state: setData, link: setLinkUp });
        // GPU 감지(nvidia-smi)는 처음 한 번 1초 가까이 걸린다. 화면을 먼저 띄우고 채운다
        api.get<SystemInfo>("/system").then(setSystem).catch(() => {});
      })
      .catch((e) => setReady(String(e?.message ?? e)));
    return () => stop?.();
  }, []);

  // 변환 중 추가분처럼 백엔드가 나중에 알리는 것
  useEffect(() => {
    if (!data) return;
    const last = data.notices.at(-1)?.id ?? 0;
    if (seenNotice.current === null) {
      seenNotice.current = last; // 화면을 다시 열었을 때 지난 알림을 또 띄우지 않는다
      return;
    }
    for (const n of data.notices) if (n.id > seenNotice.current) alert(n.text);
    seenNotice.current = Math.max(seenNotice.current, last);
  }, [data, alert]);

  // 변환 중에 창을 닫으면 확인을 받는다
  useEffect(() => {
    if (!inTauri) return;
    let unlisten: (() => void) | undefined;
    let gone = false;
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) =>
      getCurrentWindow()
        .onCloseRequested((e) => {
          if (runningRef.current) {
            e.preventDefault();
            setAskClose(true);
          }
        })
        .then((u) => (gone ? u() : (unlisten = u))),
    );
    return () => {
      gone = true;
      unlisten?.();
    };
  }, []);

  const closeNow = useCallback(async () => {
    try {
      await api.post("/batch/stop");
    } catch {
      /* 어차피 닫는다. ffmpeg 는 백엔드와 함께 정리된다 */
    }
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().destroy();
  }, []);

  const ctx: AppCtx | null = useMemo(() => (data ? { data, system, screen, go: setScreen, alert, act } : null),
    [data, system, screen, alert, act]);

  if (ready !== "ok" || !ctx) return <Splash text={ready === "wait" || ready === "ok" ? "백엔드를 시작하는 중…" : ready} error={ready !== "wait" && ready !== "ok"} />;

  return (
    <Ctx.Provider value={ctx}>
      <div className="shell">
        <Sidebar />
        <div className="col">
          <main className="main">
            {/* 화면은 모두 붙여 두고 숨긴다. 입력·필터·스크롤 위치가 화면을 오가도 남는다 */}
            <div className="screen-slot" hidden={screen !== "queue"}><QueueScreen /></div>
            <div className="screen-slot page" hidden={screen !== "settings"}><SettingsScreen /></div>
            <div className="screen-slot page" hidden={screen !== "help"}><HelpScreen /></div>
          </main>
          <div className="foot">
            {/* 대기열 화면에서는 같은 정보가 '지금 변환 중' 카드로 크게 보이므로 숨긴다 */}
            {running && screen !== "queue" && <RunLine />}
            <Monitor linkUp={linkUp} />
          </div>
        </div>
      </div>
      {!linkUp && <div className="offline" role="status">백엔드와 연결이 끊겼습니다. 다시 연결하는 중…</div>}
      {alertText && (
        <Modal title="알림" onClose={() => setAlertText("")}
          actions={<button className="btn primary" onClick={() => setAlertText("")}>확인</button>}>
          {alertText}
        </Modal>
      )}
      {askClose && (
        <Modal title="변환 진행 중" onClose={() => setAskClose(false)}
          actions={<>
            <button className="btn" data-autofocus onClick={() => setAskClose(false)}>계속 변환</button>
            <button className="btn danger-solid" onClick={closeNow}>종료</button>
          </>}>
          {"아직 변환이 진행 중입니다.\n\n지금 종료하면 변환하던 파일은 저장되지 않습니다. 원본은 그대로 남습니다.\n종료할까요?"}
        </Modal>
      )}
    </Ctx.Provider>
  );
}

// ---------------------------------------------------------------------- 사이드바

const NAV: Record<ScreenName, { label: string; icon: string }> = {
  queue: { label: "대기열", icon: ICONS.queue },
  settings: { label: "설정", icon: ICONS.settings },
  help: { label: "도움말", icon: ICONS.help },
};

function Sidebar() {
  const { data, screen, go, act } = useApp();
  // 폭은 이 버튼으로만 바뀐다. 누르자마자 접히고, 설정에 남겨 다음 실행에도 같은 모양으로 연다
  const [shut, setShut] = useState(data.settings.sidebar === "closed");
  const toggle = () => {
    const next = !shut;
    setShut(next);
    void act(() => api.put("/settings", { sidebar: next ? "closed" : "open" }));
  };
  const item = (name: ScreenName) => (
    <button key={name} className="nav-item" aria-current={screen === name ? "page" : undefined} title={NAV[name].label} onClick={() => go(name)}>
      <Icon d={NAV[name].icon} size={shut ? 18 : 16} />
      <span>{NAV[name].label}</span>
      {name === "queue" && data.batch.running && <span className="live" aria-label="변환 중" />}
      {name === "queue" && data.items.length ? <span className="nav-count">{data.items.length}</span> : null}
    </button>
  );
  return (
    <nav className={`side${shut ? " shut" : ""}`} aria-label="주 메뉴">
      <div className="side-top">
        <Logo />
        {!shut && (
          <div className="brand-name">
            <b>VIDEO CV</b>
            <span>NVENC 영상 변환기</span>
          </div>
        )}
        <button className="side-toggle" onClick={toggle} aria-label={shut ? "사이드바 펼치기" : "사이드바 접기"} aria-expanded={!shut}>
          <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 5h16v14H4zM9 5v14" /><path d={shut ? "M13 10l2 2-2 2" : "M16 10l-2 2 2 2"} />
          </svg>
        </button>
      </div>
      <div className="side-group">
        <span>변환</span>
        {item("queue")}
      </div>
      <div className="side-group">
        <span>앱</span>
        {item("settings")}
        {item("help")}
      </div>
      <span className="side-ver">V{VERSION}</span>
    </nav>
  );
}

// ---------------------------------------------------------------------- 하단: 변환 중 한 줄

function RunLine() {
  const { data, go, act } = useApp();
  const b = data.batch;
  const active = data.items.filter((i) => i.status === "converting");
  const title = b.stop_requested ? "중단하는 중…"
    : active.length > 1 ? `${active[0].name} 외 ${active.length - 1}개`
    : active[0]?.name ?? "변환할 준비 중…";
  return (
    <div className="runline" aria-label="변환 중">
      <span className="live" aria-hidden />
      <span className="order">{b.finished} / {b.total}개</span>
      <Ellipsis className={`title${b.stop_requested ? " danger" : ""}`} title={title}>{title}</Ellipsis>
      <Bar value={b.overall} tone="s" label="전체 진행률" />
      <span className="stat">{Math.round(b.overall * 100)}% · 동시 {b.jobs}개</span>
      <span className="btns">
        <button className="btn sm cyan-ghost" onClick={() => go("queue")}>대기열 보기</button>
        <button className="btn sm danger" disabled={b.stop_requested} onClick={() => act(() => api.post("/batch/stop"))}>중단</button>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------- 하단: 상태 줄

function Monitor({ linkUp }: { linkUp: boolean }) {
  const { data, system: sys } = useApp();
  const b = data.batch;
  let svc = "백엔드 연결됨 · 대기 중";
  let tone = "ok";
  if (!linkUp) {
    svc = "백엔드 연결 끊김";
    tone = "err";
  } else if (b.running) svc = b.stop_requested ? "백엔드 연결됨 · 중단하는 중" : "백엔드 연결됨 · 변환 중";

  return (
    <footer className="monitor" aria-label="상태">
      <span className="svc"><span className={`live ${tone}`} aria-hidden />{svc}</span>
      {b.running && (
        <span className="meter">
          <b>QUEUE</b>
          <span className="track" aria-hidden><span style={{ width: `${Math.round(b.overall * 100)}%` }} /></span>
          <span className="val">{Math.round(b.overall * 100)}%</span>
        </span>
      )}
      {sys && (
        <span className="monitor-right">
          <span className={sys.gpu ? undefined : "warn"}>{sys.gpu ? `${sys.gpu} · VRAM ${(sys.vram_mb / 1024).toFixed(0)}GB` : "NVIDIA GPU 없음 (CPU 변환)"}</span>
          {sys.ram_gb > 0 && <span>RAM {sys.ram_gb.toFixed(0)}GB</span>}
          <span className={sys.ffmpeg && sys.ffprobe ? undefined : "danger"}>{sys.ffmpeg && sys.ffprobe ? "FFmpeg 준비됨" : "FFmpeg 없음"}</span>
        </span>
      )}
    </footer>
  );
}

function Splash({ text, error }: { text: string; error?: boolean }) {
  return (
    <div className="splash">
      <Logo size={60} />
      <p className={error ? "err" : undefined}>{text}</p>
    </div>
  );
}

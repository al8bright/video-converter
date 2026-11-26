import { useApp } from "./ctx";
import { eyebrow, Page } from "./ui";

export function HelpScreen() {
  const { system } = useApp();
  const exts = system?.extensions.join(" ") ?? ".mkv .avi .mov .wmv .mp4 .m4v .ts";
  return (
    <Page title="도움말" eyebrow={eyebrow("HELP", "설정 안내와 성능 팁")}>
      <section className="card help">
        <h2>어떻게 변환하나요</h2>
        <ul>
          <li>NVIDIA 그래픽카드에 들어 있는 영상 인코더(NVENC)로 H.264 mp4를 만듭니다.</li>
          <li>해상도 제한보다 큰 영상은 비율을 지켜 줄이고, 최대 비트레이트에 맞춰 다시 인코딩합니다.</li>
          <li>
            비트레이트가 4 Mbps 이하이고 줄일 필요가 없는 영상은 화질 손실과 시간을 아끼려고 다시 인코딩하지 않고
            mp4로 옮겨 담습니다(대기열의 '할 일'이 '복사'). 오디오 트랙과 텍스트 자막도 함께 옮깁니다.
          </li>
          <li>그림 자막(블루레이의 PGS 등)은 mp4에 담을 수 없어 빠집니다.</li>
          <li>결과는 임시 파일에 먼저 쓰고, 다 만든 뒤 확인한 다음에 제 이름으로 바꿉니다. 원본 삭제도 그 뒤에만 합니다.</li>
        </ul>
      </section>

      <section className="card help">
        <h2>GPU 사용률과 발열</h2>
        <ul>
          <li>NVENC는 그래픽카드 안의 전용 칩이라, 변환하는 동안 낼 수 있는 최대 속도로 돕니다.</li>
          <li>'사용률 70%로 고정' 같은 직접 제한은 할 수 없습니다.</li>
          <li>발열이나 부하를 줄이려면 설정의 '동시 변환'을 1~2로 낮추세요.</li>
        </ul>
      </section>

      <section className="card help">
        <h2>변환이 실패할 때</h2>
        <ul>
          <li>GPU 디코딩이 안 되면 CPU 디코딩 + NVENC로, NVENC도 안 되면 CPU 인코딩(libx264)으로 자동으로 다시 시도합니다. CPU 인코딩은 훨씬 느립니다.</li>
          <li>10분 동안 진행이 없으면 멈춘 것으로 보고 끝냅니다.</li>
          <li>실패한 파일은 대기열에서 사유를 확인할 수 있고, '변환 시작'을 다시 누르면 다시 변환합니다.</li>
          <li>FFmpeg가 남긴 자세한 오류는 <span className="mono">%APPDATA%\VideoConverter\conversion_errors.log</span>에 쌓입니다.</li>
        </ul>
      </section>

      <section className="card help">
        <h2>넣을 수 있는 파일</h2>
        <p className="mono">{exts}</p>
        <p>폴더를 넣으면 하위 폴더까지 찾아 위 형식의 파일만 담습니다. 같은 파일은 한 번만 담깁니다.</p>
      </section>
    </Page>
  );
}

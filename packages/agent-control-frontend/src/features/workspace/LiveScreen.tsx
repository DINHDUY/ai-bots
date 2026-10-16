import { useEffect, useRef, useState } from "react";
import { CaptureImage } from "../../components/ui/CaptureImage";
import { retainedShot, type RetainedCapture } from "../../session/v2";
import type { Shot } from "../../session/reduce";
import { emptyView, useWorkspaceUi } from "../../session/workspaceUiStore";
import { clockLabel } from "../../session/selectors";
import { EmptyState } from "../../components/ui/EmptyState";
import { Icon } from "../../components/ui/Icon";
import styles from "./workspace.module.css";
import { api } from "../../api/client";
import { useSessionStore } from "../../session/store";
import { humanInput, useHumanControl } from "../../session/humanControl";

export function LiveScreen({
  botId,
  shots,
  dropped,
  historical,
  windows = false,
  macos = false,
}: {
  botId: string;
  shots: Shot[];
  dropped: number;
  historical: boolean;
  windows?: boolean;
  macos?: boolean;
}) {
  const view = useWorkspaceUi((state) => state.bots[botId] ?? emptyView);
  const patch = useWorkspaceUi((state) => state.patch);
  const session = useSessionStore((state) => state.sessions[botId]);
  const [older, setOlder] = useState<Shot[]>([]);
  const [unavailable, setUnavailable] = useState<Set<string>>(new Set());
  const [imageValid, setImageValid] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [historyEnd, setHistoryEnd] = useState(false);
  const [historyBefore, setHistoryBefore] = useState<number | null>(null);
  const selectOlder = useRef(false);
  const visible = [
    ...new Map([...older, ...shots].map((shot) => [shot.id, shot])).values(),
  ].filter(
    (shot) =>
      !unavailable.has(shot.id) &&
      !session?.removedCaptureIds?.includes(shot.id) &&
      (!shot.expiresAt || Date.parse(shot.expiresAt) > Date.now()),
  );
  const film = older.length
    ? visible.filter((shot) => older.some((old) => old.id === shot.id))
    : visible;
  const selected = visible.find((shot) => shot.id === view.shotId);
  const shown = view.shotId ? selected : visible.at(-1);
  function removeCapture(id: string) {
    if (shown?.id === id && control?.ready)
      humanInput(botId, { kind: "release" });
    setUnavailable((current) => new Set([...current, id].slice(-500)));
    useSessionStore.getState().removeCapture(botId, id);
  }
  const [now, setNow] = useState(Date.now());
  const [captureError, setCaptureError] = useState("");
  const [surface, setSurface] = useState(windows ? "desktop" : "browser");
  const control = useHumanControl((state) => state.bots[botId]);
  useEffect(() => {
    if (historyBefore === null) {
      setOlder([]);
      setHistoryEnd(false);
      return;
    }
    const abort = new AbortController();
    setLoadingOlder(true);
    void api<RetainedCapture[]>(
      `/api/bots/${botId}/captures?before_sequence=${historyBefore}`,
      { signal: abort.signal },
    )
      .then((rows) => {
        if (abort.signal.aborted) return;
        const page = rows.slice(0, 30);
        setOlder(page.reverse().map(retainedShot));
        setHistoryEnd(rows.length < 30);
        if (selectOlder.current && page.length)
          patch(botId, { shotId: page.at(-1)!.capture_id });
        selectOlder.current = false;
      })
      .catch((error) => {
        if (!abort.signal.aborted) setCaptureError(String(error));
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoadingOlder(false);
      });
    return () => abort.abort();
  }, [
    botId,
    historyBefore,
    session?.capturesInvalidation,
    session?.connection,
    patch,
  ]);
  function loadOlder() {
    const sequence = visible[0]?.storageSequence;
    if (!sequence) return;
    selectOlder.current = true;
    setHistoryBefore(sequence);
  }
  async function captureNow() {
    try {
      await api(
        `/api/bots/${botId}/computer/capture?surface=${windows ? "desktop" : surface}`,
        {
          method: "POST",
          body: JSON.stringify({ request_id: crypto.randomUUID() }),
        },
      );
      setCaptureError("");
    } catch (error) {
      setCaptureError(String(error));
    }
  }
  const interactive =
    imageValid &&
    !!shown &&
    !!control?.ready &&
    !historical &&
    !selected &&
    !shown?.capture?.transform &&
    shown?.capture?.surface_id === control.lease?.surface_id;
  function pointer(event: React.PointerEvent<HTMLImageElement>, kind: string) {
    if (!interactive || !shown?.capture) return;
    event.preventDefault();
    event.currentTarget.focus();
    const rect = event.currentTarget.getBoundingClientRect();
    const scale = Math.min(
      rect.width / shown.capture.width,
      rect.height / shown.capture.height,
    );
    const x =
      (event.clientX -
        rect.left -
        (rect.width - shown.capture.width * scale) / 2) /
      scale;
    const y =
      (event.clientY -
        rect.top -
        (rect.height - shown.capture.height * scale) / 2) /
      scale;
    if (x < 0 || y < 0 || x >= shown.capture.width || y >= shown.capture.height)
      return;
    if (kind === "down") event.currentTarget.setPointerCapture(event.pointerId);
    humanInput(botId, {
      kind,
      x,
      y,
      button: ["left", "middle", "right"][event.button] ?? "left",
    });
  }
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setImageValid(false);
  }, [shown?.id]);
  const age =
    shown?.at === undefined
      ? ""
      : Math.max(0, Math.floor((now - shown.at) / 1000));
  const ageText =
    age === ""
      ? ""
      : age < 60
        ? "just received"
        : `${Math.floor(age / 60)}m since received`;
  if (view.shotId && !shown)
    return (
      <div className={styles.screenEmpty}>
        <p role="status">Screenshot no longer available</p>
        <button onClick={() => patch(botId, { shotId: null })}>
          View latest
        </button>
      </div>
    );
  if (!shown)
    return (
      <div className={styles.screenEmpty}>
        <EmptyState
          icon="computer"
          title={
            windows
              ? (macos ? "Your Mac screen appears here" : "Your Windows screen appears here")
              : "Your bot’s computer appears here"
          }
        >
          {windows
            ? macos ? "In Bot settings, pair and select your Mac. In the macOS companion, select a window, enable Share screen, and grant Screen Recording and Accessibility permissions. Choose Connect Mac here; enable Allow agent control locally before running a task." : "In Bot settings, select your paired PC and click Use this PC. In the Windows companion, select a window and enable Share screen. Then choose Connect Windows PC here to view captures. Enable Allow agent control locally before sending a task."
            : "Screen captures arrive as your bot uses its sandbox. Send a task to get started."}
        </EmptyState>
        {session?.health?.compatible ? (
          <button onClick={() => void captureNow()}>Capture now</button>
        ) : null}
        {captureError ? <p role="alert">{captureError}</p> : null}
      </div>
    );
  return (
    <section
      className={styles.screenView}
      aria-label={macos ? "Mac captures" : windows ? "Windows captures" : "Sandbox captures"}
    >
      <div className={styles.screenToolbar}>
        <div className={styles.screenToolbarInfo}>
          {shown.capture ? (
            <span>
              {shown.capture.surface_kind === "browser" ? "Browser" : "Desktop"}
            </span>
          ) : null}
          <span>
            <Icon name="eye" />
            {historical
              ? "Previous capture"
              : selected
                ? "Selected capture"
                : "Latest capture"}
          </span>
        </div>
        <div className={styles.screenToolbarActions}>
          {session?.health?.compatible ? (
            <>
              <select
                aria-label="Capture surface"
                value={surface}
                onChange={(event) => setSurface(event.target.value)}
              >
                {!windows ? <option value="browser">Browser</option> : null}
                <option value="desktop">Desktop</option>
              </select>
              <button onClick={() => void captureNow()}>Capture now</button>
            </>
          ) : null}
          <button
            disabled={!imageValid}
            className="ghost"
            onClick={() => patch(botId, { zoom: !view.zoom })}
            aria-pressed={view.zoom}
          >
            {view.zoom ? "Fit" : "Zoom"}
          </button>
        </div>
      </div>
      <div
        className={`${styles.screenImage} ${view.zoom ? styles.zoomed : ""}`}
        tabIndex={0}
      >
        <CaptureImage
          expiresAt={shown.expiresAt}
          onUnavailable={() => removeCapture(shown.id)}
          onValidityChange={setImageValid}
          onLoadFailure={() => {
            if (control?.ready) humanInput(botId, { kind: "release" });
          }}
          src={shown.src}
          tabIndex={interactive ? 0 : -1}
          style={{ cursor: interactive ? "crosshair" : "default" }}
          onPointerDown={(event) => pointer(event, "down")}
          onPointerUp={(event) => pointer(event, "up")}
          onPointerMove={(event) => {
            if (event.buttons) pointer(event, "move");
          }}
          onPointerCancel={() => {
            if (interactive) humanInput(botId, { kind: "release" });
          }}
          onContextMenu={(event) => {
            if (interactive) event.preventDefault();
          }}
          onKeyDown={(event) => {
            if (interactive) {
              event.preventDefault();
              if (!event.repeat)
                humanInput(botId, { kind: "key_down", key: event.key });
            }
          }}
          onKeyUp={(event) => {
            if (interactive) {
              event.preventDefault();
              humanInput(botId, { kind: "key_up", key: event.key });
            }
          }}
          onBlur={() => {
            if (interactive) humanInput(botId, { kind: "release" });
          }}
          onWheel={(event) => {
            if (interactive)
              humanInput(botId, {
                kind: "wheel",
                dx: Math.max(-2000, Math.min(2000, event.deltaX)),
                dy: Math.max(-2000, Math.min(2000, event.deltaY)),
              });
          }}
          alt={`${macos ? "Mac" : windows ? "Windows" : "Sandbox"} capture${shown.at ? ` received at ${clockLabel(shown.at)}` : ""}`}
        />
        {imageValid &&
        !historical &&
        !selected &&
        shown.capture?.surface_kind === "desktop" &&
        shown.capture.cursor &&
        now - Date.parse(shown.capture.captured_at) < 30000 ? (
          <svg
            aria-label="Observed desktop cursor"
            viewBox={`0 0 ${shown.capture.width} ${shown.capture.height}`}
            style={{
              position: "absolute",
              pointerEvents: "none",
              left: 0,
              top: 0,
              width: view.zoom ? shown.capture.width : "100%",
              height: view.zoom ? shown.capture.height : "100%",
            }}
          >
            <path
              transform={`translate(${shown.capture.cursor.x},${shown.capture.cursor.y})`}
              d="M0 0 L0 18 L5 13 L9 21 L12 19 L8 11 L15 11 Z"
              fill="white"
              stroke="black"
              strokeWidth="1.5"
            />
          </svg>
        ) : null}
      </div>
      <div className={styles.captureMeta}>
        {interactive ? (
          <span>Human input enabled</span>
        ) : (
          <span>View only</span>
        )}
        {shown.capture ? (
          <span>
            {shown.capture.width} × {shown.capture.height} · Captured{" "}
            {clockLabel(Date.parse(shown.capture.captured_at))}
            {shown.capture.transform?.view_only ? " · Cropped, view only" : ""}
          </span>
        ) : null}
        <span>{ageText || "Received in this page session"}</span>
        {view.shotId ? (
          <button
            className="ghost"
            onClick={() => patch(botId, { shotId: null })}
          >
            Back to latest
          </button>
        ) : (
          <span className={styles.captureIndicator}>Screenshot</span>
        )}
      </div>
      {captureError ? <p role="alert">{captureError}</p> : null}
      {shown.capture?.url ? (
        <p className={styles.captureNote}>
          {shown.capture.title} · {shown.capture.url}
        </p>
      ) : null}
      {film.length > 1 ? (
        <div className={styles.film} aria-label="Capture history">
          {film.map((shot, index) => (
            <button
              key={shot.id}
              type="button"
              aria-label={`Capture ${dropped + index + 1}`}
              aria-pressed={shown.id === shot.id}
              onClick={() => patch(botId, { shotId: shot.id })}
            >
              <CaptureImage
                src={shot.src}
                expiresAt={shot.expiresAt}
                onUnavailable={() => removeCapture(shot.id)}
                retryable={false}
                alt=""
                loading="lazy"
              />
            </button>
          ))}
        </div>
      ) : null}
      {historyBefore !== null ? (
        <button
          onClick={() => {
            setHistoryBefore(null);
            patch(botId, { shotId: null });
          }}
        >
          Latest captures
        </button>
      ) : null}
      {!historyEnd && visible[0]?.storageSequence ? (
        <button disabled={loadingOlder} onClick={() => void loadOlder()}>
          {loadingOlder ? "Loading..." : "Load older captures"}
        </button>
      ) : null}
      {dropped > 0 ? (
        <p className={styles.captureNote}>
          Showing the most recent {shots.length} captures; {dropped} earlier
          captures not loaded.
        </p>
      ) : null}
    </section>
  );
}

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Attachments } from "./Attachments";
import { AgentPauseNotice } from "./AgentPauseNotice";
import type { BotStatus, ConnectionStatus } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { useWorkspaceUi } from "../../session/workspaceUiStore";
import { Icon } from "../../components/ui/Icon";
import styles from "./chat.module.css";

type Recognizer = {
  lang: string;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }>>;
      }) => void)
    | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  abort: () => void;
};
function recognitionCtor(): (new () => Recognizer) | null {
  const host = window as Window & {
    SpeechRecognition?: new () => Recognizer;
    webkitSpeechRecognition?: new () => Recognizer;
  };
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null;
}
export function Composer({
  botId,
  botName,
  defaultPrompt,
  status,
  connection,
}: {
  botId: string;
  botName: string;
  defaultPrompt?: string;
  status: BotStatus;
  connection: ConnectionStatus;
}) {
  const draft = useWorkspaceUi((state) => state.bots[botId]?.draft ?? "");
  const patch = useWorkspaceUi((state) => state.patch);
  const sendPrompt = useSessionStore((state) => state.sendPrompt);
  const session = useSessionStore((state) => state.sessions[botId]);
  const [attachments, setAttachments] = useState<
    { id: string; path: string }[]
  >([]);
  useEffect(() => setAttachments([]), [botId, session?.sessionId]);
  const submitting = useSessionStore(
    (state) => state.sessions[botId]?.submitting,
  );
  const commandError = useSessionStore(
    (state) => state.sessions[botId]?.commandError,
  );
  const computerFailed = useSessionStore(
    (state) => state.sessions[botId]?.computerStatus === "failed",
  );
  const stop = useSessionStore((state) => state.stop);
  const [listening, setListening] = useState(false);
  const [speechError, setSpeechError] = useState("");
  const recognizer = useRef<Recognizer | null>(null);
  const Speech = recognitionCtor();
  const busy =
    status === "running" ||
    status === "awaiting" ||
    status === "stopping" ||
    submitting;
  const ready = connection === "connected";
  useEffect(
    () => () => {
      if (recognizer.current) {
        recognizer.current.onresult = null;
        recognizer.current.onend = null;
        recognizer.current.onerror = null;
        recognizer.current.abort();
      }
    },
    [botId],
  );
  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy || computerFailed || !draft.trim()) return;
    const sent = draft;
    if (
      await sendPrompt(
        botId,
        sent,
        attachments.map((item) => item.id),
      )
    ) {
      setAttachments([]);
      if (useWorkspaceUi.getState().bots[botId]?.draft === sent)
        patch(botId, { draft: "" });
    }
  }
  function dictate() {
    if (!Speech || listening) return;
    const recognition = new Speech();
    recognizer.current = recognition;
    recognition.lang = "en-US";
    recognition.onresult = (event) => {
      const text =
        event.results[event.results.length - 1]?.[0]?.transcript ?? "";
      const current = useWorkspaceUi.getState().bots[botId]?.draft ?? "";
      if (text) patch(botId, { draft: current ? `${current} ${text}` : text });
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => {
      setListening(false);
      setSpeechError("Dictation unavailable. You can type your message.");
    };
    setListening(true);
    setSpeechError("");
    try {
      recognition.start();
    } catch {
      setListening(false);
      setSpeechError("Could not start dictation.");
    }
  }
  return (
    <div className={styles.composerWrap}>
      {session?.protocol === 2 ? <AgentPauseNotice botId={botId} /> : null}
      {attachments.map((item) => (
        <span key={item.id}>
          {item.path}{" "}
          <button
            onClick={() =>
              setAttachments((values) =>
                values.filter((value) => value.id !== item.id),
              )
            }
          >
            Remove attachment
          </button>
        </span>
      ))}
      <form className={styles.composer} onSubmit={onSubmit}>
        <label>
          <span className="sr-only">Message</span>
          <textarea
            aria-label="Message"
            name="prompt"
            rows={2}
            value={draft}
            placeholder={`Message ${botName}…`}
            onChange={(event) => patch(botId, { draft: event.target.value })}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
        </label>
        <div className={styles.composerToolbar}>
          {defaultPrompt?.trim() ? (
            <button
              type="button"
              className="ghost"
              onClick={() => patch(botId, { draft: defaultPrompt })}
            >
              <Icon name="file" />
              Default Prompt
            </button>
          ) : null}
          {session?.health?.services.files && session.sessionId ? (
            <Attachments
              botId={botId}
              sid={session.sessionId}
              disabled={!!busy || !ready}
              onUploaded={(item) =>
                setAttachments((values) => [...values, item].slice(-10))
              }
            />
          ) : null}
          <span className="spacer" />
          <button
            type="button"
            className="ghost"
            disabled={!busy || !ready}
            onClick={() => stop(botId)}
          >
            <Icon name="close" />
            Stop
          </button>
          {Speech ? (
            <button
              type="button"
              className="icon-button ghost"
              aria-label={listening ? "Listening" : "Dictate"}
              onClick={dictate}
              disabled={listening}
            >
              <Icon name="mic" />
            </button>
          ) : null}
          <button
            className="primary icon-button"
            type="submit"
            aria-label="Send"
            disabled={!ready || busy || computerFailed || !draft.trim()}
          >
            <Icon name="up" />
          </button>
        </div>
      </form>
      <div className={styles.composerCaption}>
        <span data-connected={ready}>
          <i className="dot" />
          {ready
            ? "Connected to control"
            : connection === "reconnecting"
              ? "Reconnecting…"
              : connection === "disconnected"
                ? "Disconnected from control"
                : "Connecting to control…"}
        </span>
        <span>Enter to send · Shift Enter for a new line</span>
      </div>
      {speechError ? (
        <p role="status" className="error">
          {speechError}
        </p>
      ) : null}
      {commandError ? (
        <p role="alert" className="error">
          {commandError}
        </p>
      ) : null}
    </div>
  );
}

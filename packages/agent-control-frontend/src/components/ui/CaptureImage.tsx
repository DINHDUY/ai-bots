import { useEffect, useRef, useState, type ImgHTMLAttributes } from "react";

type Props = ImgHTMLAttributes<HTMLImageElement> & {
  retryable?: boolean;
  onLoadFailure?: () => void;
  expiresAt?: string | null;
  onUnavailable?: () => void;
  onValidityChange?: (valid: boolean) => void;
};

/** A failed image never leaves a browser broken-image glyph in the workspace. */
export function CaptureImage({
  retryable = true,
  src,
  expiresAt,
  onUnavailable,
  onValidityChange,
  onLoadFailure,
  ...props
}: Props) {
  const [failure, setFailure] = useState<
    "checking" | "gone" | "network" | null
  >(null);
  const [attempt, setAttempt] = useState(0);
  const callbacks = useRef({ onUnavailable, onValidityChange, onLoadFailure });
  callbacks.current = { onUnavailable, onValidityChange, onLoadFailure };
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setFailure(null);
    callbacks.current.onValidityChange?.(false);
    let timer: ReturnType<typeof setTimeout> | undefined;
    function expire() {
      if (!expiresAt) return;
      const remaining = Date.parse(expiresAt) - Date.now();
      if (remaining > 0)
        timer = setTimeout(expire, Math.min(remaining, 2_147_483_647));
      else {
        setFailure("gone");
        callbacks.current.onValidityChange?.(false);
        callbacks.current.onUnavailable?.();
      }
    }
    expire();
    return () => {
      generation.current++;
      clearTimeout(timer);
      controller.current?.abort();
    };
  }, [src, expiresAt]);

  async function failed() {
    if (failure || !src) return;
    const version = generation.current;
    setFailure("checking");
    callbacks.current.onLoadFailure?.();
    callbacks.current.onValidityChange?.(false);
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    try {
      const response = await fetch(src, {
        credentials: "include",
        cache: "no-store",
        signal: abort.signal,
      });
      void response.body?.cancel();
      if (version !== generation.current || abort.signal.aborted) return;
      if (response.status === 404 || response.status === 410) {
        setFailure("gone");
        callbacks.current.onUnavailable?.();
      } else setFailure("network");
    } catch {
      if (version === generation.current && !abort.signal.aborted)
        setFailure("network");
    }
  }
  if (failure)
    return (
      <span className="capture-unavailable" role="status">
        {failure === "gone"
          ? "Screenshot no longer available"
          : failure === "checking"
            ? "Checking screenshot…"
            : "Screenshot could not be loaded"}
        {failure === "network" && retryable ? (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setFailure(null);
              setAttempt(attempt + 1);
            }}
          >
            Retry
          </button>
        ) : null}
      </span>
    );
  return (
    <img
      {...props}
      key={`${src}:${attempt}`}
      src={src}
      crossOrigin="use-credentials"
      onError={() => void failed()}
      onLoad={(event) => {
        callbacks.current.onValidityChange?.(true);
        props.onLoad?.(event);
      }}
    />
  );
}

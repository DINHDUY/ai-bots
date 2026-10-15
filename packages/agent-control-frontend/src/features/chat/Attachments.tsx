import { useEffect, useRef, useState } from "react";
import { apiBase } from "../../api/client";
import { Icon } from "../../components/ui/Icon";
import styles from "./chat.module.css";

export function Attachments({
  botId,
  sid,
  disabled,
  onUploaded,
}: {
  botId: string;
  sid: string;
  disabled: boolean;
  onUploaded: (item: { id: string; path: string }) => void;
}) {
  const [progress, setProgress] = useState<number>();
  const [error, setError] = useState("");
  const active = useRef<XMLHttpRequest | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  return (
    <>
      <button
        type="button"
        className="icon-button ghost"
        aria-label="Upload attachment"
        title="Upload attachment"
        disabled={disabled || progress !== undefined}
        onClick={() => fileInput.current?.click()}
      >
        <Icon name="uploadFile" />
      </button>
      <input
        ref={fileInput}
        type="file"
        hidden
        aria-label="Choose attachment"
        disabled={disabled || progress !== undefined}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          if (file.size > 64 * 1024 * 1024) {
            setError("Maximum attachment size is 64 MiB.");
            return;
          }
          const form = new FormData();
          form.set("file", file);
          form.set("path", file.name);
          form.set("expected_revision", "missing");
          form.set("request_id", crypto.randomUUID());
          const request = new XMLHttpRequest();
          active.current = request;
          request.withCredentials = true;
          request.open(
            "POST",
            `${apiBase()}/api/bots/${botId}/sessions/${sid}/uploads`,
          );
          setProgress(0);
          setError("");
          request.upload.onprogress = (event) => {
            if (event.lengthComputable)
              setProgress(Math.round((event.loaded / event.total) * 100));
          };
          request.onload = () => {
            setProgress(undefined);
            try {
              const result = JSON.parse(request.responseText);
              if (request.status >= 200 && request.status < 300)
                onUploaded(result);
              else setError(result.detail ?? "Upload failed.");
            } catch {
              setError("Upload response could not be confirmed.");
            }
          };
          request.onerror = () => {
            setProgress(undefined);
            setError(
              "Upload could not be confirmed. Refresh files before retrying.",
            );
          };
          request.onabort = () => {
            setProgress(undefined);
            setError(
              "Upload cancelled. Refresh files to check whether it committed.",
            );
          };
          request.send(form);
          event.target.value = "";
        }}
      />
      {progress !== undefined || error ? (
        <div className={styles.uploadFeedback}>
          {progress !== undefined ? (
            <>
              <span role="status">Uploading attachment… {progress}%</span>
              <button type="button" onClick={() => active.current?.abort()}>
                Cancel upload
              </button>
            </>
          ) : null}
          {error ? <p role="alert">{error}</p> : null}
        </div>
      ) : null}
    </>
  );
}

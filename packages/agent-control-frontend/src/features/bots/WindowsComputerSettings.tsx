import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import styles from "./dialog.module.css";

import { windowsStatus, type WindowsDevice } from "./windowsStatus";

export function WindowsComputerSettings({
  botId,
  framework,
  disabled = false,
  onBusyChange,
}: {
  botId: string;
  framework: string;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const client = useQueryClient();
  const isUfo = framework === "ufo";
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<{ windows_computers?: boolean }>("/api/capabilities"),
    staleTime: 60_000,
  });
  const available = capabilities.data?.windows_computers === true;
  const needsUpdate =
    !capabilities.isError ||
    (capabilities.error instanceof ApiError && capabilities.error.status === 404);
  const devices = useQuery({
    queryKey: ["windows-computers"],
    queryFn: () => api<{ computers: WindowsDevice[] }>("/api/computers"),
    enabled: available,
    refetchInterval: 3000,
  });
  const config = useQuery({
    queryKey: ["compute-config", botId],
    enabled: available && isUfo,
    queryFn: () =>
      api<{ device_id: string | null; revision: number }>(
        `/api/bots/${botId}/compute-config`,
      ),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  const deviceId = selected ?? config.data?.device_id ?? "";
  const assigned = isUfo && config.data?.device_id;
  async function mutate(path: string, body: object, paired = false) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ code: string; expires_at: string }>(path, {
        method: "POST",
        body: JSON.stringify({ request_id: crypto.randomUUID(), ...body }),
      });
      if (paired) setCode(result);
      await client.invalidateQueries({ queryKey: ["windows-computers"] });
      await client.invalidateQueries({ queryKey: ["compute-config", botId] });
      await client.invalidateQueries({ queryKey: ["computer", botId] });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset className={styles.computerSettings} disabled={disabled}>
      <legend>This Windows PC</legend>
      <p>
        Pair a Windows PC with your account. Sharing and control are enabled
        locally in the Windows companion.
      </p>
      {!isUfo ? (
        <p>
          To control a paired PC, create a new bot and choose{" "}
          <strong>Microsoft UFO · Windows desktop</strong> under Framework.
          This bot uses {framework} and cannot control a Windows desktop.
        </p>
      ) : (
        <p>
          Pairing adds a PC to your account. Select it below and click <strong>Save</strong> to assign it to this bot,
          or use <strong>Use this PC</strong> to apply only the PC selection.
          In the Windows companion, select a window or the whole primary display,
          enable <strong>Share screen</strong>, then enable <strong>Allow agent control</strong> to run tasks.
        </p>
      )}
      {!isUfo && available ? <Link to="/overview?newBot=ufo">Create Windows bot</Link> : null}
      <div className={styles.computerActions}>
        <button
          type="button"
          disabled={busy || !available}
          onClick={() => void mutate("/api/computers/enrollments", {}, true)}
        >
          Pair a Windows PC
        </button>
      </div>
      {!available ? (
        <div>
          <p role={capabilities.isError && !needsUpdate ? "alert" : "status"}>
            {capabilities.isPending
              ? "Checking Windows pairing availability…"
              : needsUpdate
                ? "Backend update required. Restart the updated control backend to enable Windows pairing."
                : `Could not load Windows pairing: ${capabilities.error?.message}`}
          </p>
          {!capabilities.isPending ? (
            <button type="button" onClick={() => void capabilities.refetch()}>
              Retry Windows pairing
            </button>
          ) : null}
        </div>
      ) : null}
      {code ? (
        <div role="status">
          <p>
            Run <code>agentbot-windows pair</code> on this PC and enter this
            one-time code. It expires at{" "}
            {new Date(code.expires_at).toLocaleTimeString()}.
          </p>
          <input
            aria-label="One-time pairing code"
            readOnly
            value={code.code}
            onFocus={(e) => e.target.select()}
          />
          <button type="button" onClick={() => setCode(null)}>
            Hide code
          </button>
        </div>
      ) : null}
      {available ? (
        <>
          <label>
            Paired computer
            <select
              aria-label="Paired Windows computer"
              name="windows_device_id"
              value={deviceId}
              disabled={busy}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="" disabled={!!config.data?.device_id}>Select a Windows PC</option>
              {devices.data?.computers.map((pc) => (
                <option key={pc.id} value={pc.id}>
                  {pc.name} · {windowsStatus(pc)}
                </option>
              ))}
            </select>
          </label>
          {isUfo && deviceId && deviceId !== config.data?.device_id ? (
            <p role="status">PC selection not saved. Click Save or Use this PC to apply it.</p>
          ) : null}
          <div className={styles.computerActions}>
            {isUfo ? (
              <button
                type="button"
                disabled={busy || !deviceId || !config.data || deviceId === config.data.device_id}
                onClick={() =>
                  void mutate(`/api/bots/${botId}/compute-config`, {
                    device_id: deviceId,
                    expected_revision: config.data!.revision,
                  })
                }
              >
                Use this PC
              </button>
            ) : null}
            <button
              type="button"
              disabled={busy || !deviceId}
              onClick={() => {
                if (
                  window.confirm(
                    "Revoke this PC's pairing and stop its connected bots?",
                  )
                )
                  void mutate(`/api/computers/${deviceId}/revoke`, {});
              }}
            >
              Revoke pairing
            </button>
          </div>
          {assigned ? (
            <p role="status">
              {devices.data?.computers.find((pc) => pc.id === assigned)?.name ?? "Windows PC"} is assigned to this bot.
              Close settings and choose <strong>Connect Windows PC</strong> in the Local Windows PC panel.
              Once connected, use <strong>Capture now</strong> to check the shared screen.
            </p>
          ) : isUfo && config.data ? (
            <p role="status">No Windows PC is assigned to this bot yet.</p>
          ) : null}
        </>
      ) : null}
      {error || devices.error || config.error ? (
        <p role="alert">{error || String(devices.error ?? config.error)}</p>
      ) : null}
    </fieldset>
  );
}

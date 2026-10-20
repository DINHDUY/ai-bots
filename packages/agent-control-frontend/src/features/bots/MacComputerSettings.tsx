import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import styles from "./dialog.module.css";

import type { MacDeviceList } from "../../api/macos.generated";
import { windowsStatus } from "./windowsStatus";

export function MacComputerSettings({
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
  const isMac = framework === "open_interface";
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<{ macos_computers?: boolean }>("/api/capabilities"),
    staleTime: 60_000,
  });
  const available = capabilities.data?.macos_computers === true;
  const needsUpdate =
    !capabilities.isError ||
    (capabilities.error instanceof ApiError && capabilities.error.status === 404);
  const devices = useQuery({
    queryKey: ["macos-computers"],
    queryFn: () => api<MacDeviceList>("/api/macos-computers"),
    enabled: available,
    refetchInterval: 3000,
  });
  const config = useQuery({
    queryKey: ["compute-config", botId],
    enabled: available && isMac,
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
  const assigned = isMac && config.data?.device_id;
  const pending = useRef<{ key: string; requestId: string } | null>(null);
  async function mutate(path: string, body: object, paired = false) {
    setBusy(true);
    setError("");
    const key = JSON.stringify([path, body]);
    if (pending.current?.key !== key) pending.current = {key, requestId: crypto.randomUUID()};
    try {
      const result = await api<{ code: string; expires_at: string }>(path, {
        method: "POST",
        body: JSON.stringify({ request_id: pending.current.requestId, ...body }),
      });
      pending.current = null;
      if (paired) setCode(result);
      await client.invalidateQueries({ queryKey: ["macos-computers"] });
      await client.invalidateQueries({ queryKey: ["compute-config", botId] });
      await client.invalidateQueries({ queryKey: ["computer", botId] });
    } catch (e) {
      if (e instanceof ApiError && e.status < 500) pending.current = null;
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset className={styles.computerSettings} disabled={disabled}>
      <legend>This Mac</legend>
      <p>
        Pair a Mac with your account. Sharing and control are enabled
        locally in the macOS companion.
      </p>
      <p>Screen Recording and Accessibility permissions are required in macOS System Settings. Select the sharing scope in the companion.</p>
      {!isMac ? (
        <p>
          To control a paired Mac, create a new bot and choose{" "}
          <strong>Open Interface · macOS</strong> under Framework.
          This bot uses {framework} and cannot control a macOS desktop.
        </p>
      ) : (
        <p>
          Pairing adds a Mac to your account. Select it below and click <strong>Save</strong> to assign it to this bot,
          or use <strong>Use this Mac</strong> to apply only the Mac selection.
          In the macOS companion, select a window or the whole primary display,
          enable <strong>Share screen</strong>, then enable <strong>Allow agent control</strong> to run tasks.
        </p>
      )}
      {!isMac && available ? <Link to="/overview?newBot=open_interface">Create Mac bot</Link> : null}
      <div className={styles.computerActions}>
        <button
          type="button"
          disabled={busy || !available}
          onClick={() => void mutate("/api/macos-computers/enrollments", {}, true)}
        >
          Pair a Mac
        </button>
      </div>
      {!available ? (
        <div>
          <p role={capabilities.isError && !needsUpdate ? "alert" : "status"}>
            {capabilities.isPending
              ? "Checking Mac pairing availability…"
              : needsUpdate
                ? "Backend update required. Restart the updated control backend to enable Mac pairing."
                : `Could not load Mac pairing: ${capabilities.error?.message}`}
          </p>
          {!capabilities.isPending ? (
            <button type="button" onClick={() => void capabilities.refetch()}>
              Retry Mac pairing
            </button>
          ) : null}
        </div>
      ) : null}
      {code ? (
        <div role="status">
          <p>
            Run <code>agentbot-macos pair</code> on this Mac and enter this
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
              aria-label="Paired Mac"
              name="macos_device_id"
              value={deviceId}
              disabled={busy}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="" disabled={!!config.data?.device_id}>Select a Mac</option>
              {devices.data?.computers.map((pc) => (
                <option key={pc.id} value={pc.id}>
                  {pc.name} · {windowsStatus(pc, "Mac unavailable")}
                </option>
              ))}
            </select>
          </label>
          {isMac && deviceId && deviceId !== config.data?.device_id ? (
            <p role="status">Mac selection not saved. Click Save or Use this Mac to apply it.</p>
          ) : null}
          <div className={styles.computerActions}>
            {isMac ? (
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
                Use this Mac
              </button>
            ) : null}
            <button
              type="button"
              disabled={busy || !deviceId}
              onClick={() => {
                if (
                  window.confirm(
                    "Revoke this Mac's pairing and stop its connected bots?",
                  )
                )
                  void mutate(`/api/macos-computers/${deviceId}/revoke`, {});
              }}
            >
              Revoke pairing
            </button>
          </div>
          {assigned ? (
            <p role="status">
              {devices.data?.computers.find((pc) => pc.id === assigned)?.name ?? "Mac"} is assigned to this bot.
              Close settings and choose <strong>Connect Mac</strong> in the Local Mac panel.
              Once connected, use <strong>Capture now</strong> to check the shared screen.
            </p>
          ) : isMac && config.data ? (
            <p role="status">No Mac is assigned to this bot yet.</p>
          ) : null}
        </>
      ) : null}
      {error || devices.error || config.error ? (
        <p role="alert">{error || String(devices.error ?? config.error)}</p>
      ) : null}
    </fieldset>
  );
}

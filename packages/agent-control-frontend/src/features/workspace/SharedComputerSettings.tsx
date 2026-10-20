import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { post } from "./workspaceApi";

type ComputerSettings = {
  mode: "per_bot" | "shared";
  provider: string;
  profile_id: string | null;
  ownership: "attached" | "managed";
  revision: number;
  role: string;
  limitation: string;
  attached_bot_ids: string[];
  busy: boolean;
  computer: { id: string; status: string; generation: number; scope?: string } | null;
};

const operations = ["create", "hibernate", "resume", "close", "reset", "keep-warm"] as const;

export function SharedComputerSettings({ wid, owner }: { wid: string; owner: boolean }) {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["workspace-computer", wid],
    queryFn: () => api<ComputerSettings>(`/api/workspaces/${wid}/computer`),
  });
  const settings = query.data;
  async function save(next: Partial<ComputerSettings>) {
    if (!settings) return;
    setError("");
    setNotice("");
    try {
      await post(`/api/workspaces/${wid}/computer`, {
        request_id: crypto.randomUUID(),
        expected_revision: settings.revision,
        mode: next.mode ?? settings.mode,
        provider: next.provider ?? settings.provider,
        profile_id: next.profile_id === undefined ? settings.profile_id : next.profile_id,
        ownership: next.ownership ?? settings.ownership,
      }, "PUT");
      setNotice("Workspace computer settings saved.");
      await client.invalidateQueries({ queryKey: ["workspace-computer", wid] });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }
  async function lifecycle(operation: string) {
    if (!settings) return;
    setError("");
    try {
      const result = await post<{ status: string; detail?: string }>(
        `/api/workspaces/${wid}/computer/lifecycle`,
        {
          request_id: crypto.randomUUID(),
          operation,
          generation: settings.computer?.generation ?? 0,
          minutes: 30,
        },
      );
      if (result.status !== "completed" && result.status !== "accepted") {
        throw new Error(result.detail ?? result.status);
      }
      setNotice(`${operation} ${result.status}.`);
      await query.refetch();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }
  if (!settings) return <p>Loading workspace computer…</p>;
  const shared = settings.mode === "shared";
  return (
    <section className="center-card" aria-label="Workspace computer">
      <h2>Workspace computer</h2>
      <p className="muted">{settings.limitation}</p>
      <p>
        Eligible bots in this workspace {shared ? "share one computer" : "each keep their own computer"}.
        Windows and macOS desktop bots always keep their own computer.
      </p>
      <label>
        Computer mode
        <select
          aria-label="Computer mode"
          value={settings.mode}
          disabled={!owner}
          onChange={(event) => void save({ mode: event.target.value as ComputerSettings["mode"] })}
        >
          <option value="per_bot">One computer per bot</option>
          <option value="shared">Share one computer</option>
        </select>
      </label>
      {shared ? (
        <>
          <p role="status">
            {settings.computer
              ? `Shared computer ${settings.computer.status}`
              : "No shared computer yet."}
            {settings.attached_bot_ids.length
              ? ` · ${settings.attached_bot_ids.length} attached bot${settings.attached_bot_ids.length === 1 ? "" : "s"}`
              : ""}
            {settings.busy ? " · in use" : ""}
          </p>
          {owner && settings.provider === "docker" ? (
            <div className="row">
              {operations.map((operation) => (
                <button key={operation} type="button" onClick={() => void lifecycle(operation)}>
                  {operation}
                </button>
              ))}
            </div>
          ) : null}
          {owner && settings.provider !== "docker" ? (
            <p className="muted">Manage this Azure computer with the lifecycle actions for its profile.</p>
          ) : null}
        </>
      ) : (
        <p className="muted">
          Turn on sharing only after every eligible bot computer is closed.{" "}
          <Link to="/overview">Open bots</Link>
        </p>
      )}
      {notice ? <p role="status">{notice}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}

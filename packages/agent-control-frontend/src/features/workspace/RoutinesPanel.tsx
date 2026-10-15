import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, apiBase, type Bot } from "../../api/client";
import { type ToolkitData, post, type Group, type Routine, type Definition } from "./workspaceApi";

export function RoutinesPanel({
  wid,
  bots,
  onError,
}: {
  wid: string;
  bots: Bot[];
  onError: (s: string) => void;
}) {
  const routines = useQuery({
    queryKey: ["routines", wid],
    queryFn: () => api<Routine[]>(`/api/workspaces/${wid}/routines`),
    refetchInterval: 5000,
  });
  const groups = useQuery({
    queryKey: ["groups", wid],
    queryFn: () => api<Group[]>(`/api/workspaces/${wid}/groups`),
  });
  const initial: Definition = {
    name: "",
    bot_id: bots[0]?.id,
    prompt: "",
    trigger: "manual",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    local_time: "09:00",
    interval_seconds: 3600,
    missed: "skip",
    overlap: "skip",
    enabled: true,
    resume_computer: false,
    version: 0,
  };
  const [draft, setDraft] = useState(initial);
  const toolkit = useQuery({
    queryKey: ["toolkit", draft.bot_id],
    queryFn: () => api<ToolkitData>(`/api/bots/${draft.bot_id}/toolkit`),
    enabled: !!draft.bot_id,
  });
  const policies = useQuery({
    queryKey: ["routine-policies", draft.bot_id],
    queryFn: () =>
      api<{ id: string; summary: string; revoked_at?: string }[]>(
        `/api/bots/${draft.bot_id}/approval-policies`,
      ),
    enabled: !!draft.bot_id,
  });
  const [editing, setEditing] = useState("");
  const [historyId, setHistoryId] = useState("");
  const [preview, setPreview] = useState<string[]>([]);
  const [secret, setSecret] = useState("");
  const history = useQuery({
    queryKey: ["routine-history", historyId],
    queryFn: () =>
      api<
        {
          id: string;
          state: string;
          created_at: string;
          detail: string;
          bot_id: string;
          run_id: string;
        }[]
      >(`/api/routines/${historyId}/history`),
    enabled: !!historyId,
    refetchInterval: 3000,
  });
  return (
    <div className="center-grid">
      <section className="center-card">
        <h2>{editing ? "Edit routine" : "Create a routine"}</h2>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await post(
                editing
                  ? `/api/routines/${editing}`
                  : `/api/workspaces/${wid}/routines`,
                draft,
                editing ? "PATCH" : "POST",
              );
              setEditing("");
              setDraft(initial);
              void routines.refetch();
            } catch (e) {
              onError(String(e));
            }
          }}
        >
          <label>
            Name
            <input
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label>
            Target
            <select
              value={
                draft.group_id
                  ? `group:${draft.group_id}`
                  : (draft.bot_id ?? "")
              }
              onChange={(e) =>
                setDraft({
                  ...draft,
                  skill_id: undefined,
                  connection_id: undefined,
                  approval_policy_id: undefined,
                  parameters: {},
                  trigger: draft.trigger === "event" ? "manual" : draft.trigger,
                  bot_id: e.target.value.startsWith("group:")
                    ? undefined
                    : e.target.value,
                  group_id: e.target.value.startsWith("group:")
                    ? e.target.value.slice(6)
                    : undefined,
                })
              }
            >
              {bots.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
              {groups.data?.map((g) => (
                <option key={g.id} value={`group:${g.id}`}>
                  Group: {g.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Task
            <textarea
              required={!draft.skill_id && !draft.connection_id}
              value={draft.prompt}
              onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
              placeholder={
                draft.group_id
                  ? "@group Summarize the task"
                  : "Describe the task"
              }
            />
          </label>
          {draft.bot_id ? (
            <>
              <label>
                Execution
                <select
                  value={
                    draft.skill_id
                      ? `skill:${draft.skill_id}`
                      : draft.connection_id
                        ? `connector:${draft.connection_id}`
                        : "prompt"
                  }
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      skill_id: e.target.value.startsWith("skill:")
                        ? e.target.value.slice(6)
                        : undefined,
                      connection_id: e.target.value.startsWith("connector:")
                        ? e.target.value.slice(10)
                        : undefined,
                      parameters: {},
                    })
                  }
                >
                  <option value="prompt">Agent task</option>
                  {toolkit.data?.skills
                    .filter((s) => s.installed)
                    .map((s) => (
                      <option key={s.id} value={`skill:${s.id}`}>
                        Skill: {s.name}
                      </option>
                    ))}
                  {toolkit.data?.connections
                    .filter((c) => c.status !== "revoked")
                    .map((c) => (
                      <option key={c.id} value={`connector:${c.id}`}>
                        GitHub: {c.repository}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Allowed automatic approval policy
                <select
                  value={draft.approval_policy_id ?? ""}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      approval_policy_id: e.target.value || undefined,
                    })
                  }
                >
                  <option value="">Use bot approval settings</option>
                  {policies.data
                    ?.filter((p) => !p.revoked_at)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.summary}
                      </option>
                    ))}
                </select>
              </label>
            </>
          ) : null}
          {draft.skill_id
            ? Object.keys(
                JSON.parse(
                  toolkit.data?.skills.find((s) => s.id === draft.skill_id)
                    ?.parameters ?? "{}",
                ),
              ).map((key) => (
                <label key={key}>
                  Parameter: {key}
                  <input
                    required
                    value={draft.parameters?.[key] ?? ""}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        parameters: {
                          ...draft.parameters,
                          [key]: e.target.value,
                        },
                      })
                    }
                  />
                </label>
              ))
            : null}
          {draft.connection_id ? (
            <>
              <label>
                GitHub action
                <select
                  value={draft.connector_operation ?? "list_issues"}
                  onChange={(e) =>
                    setDraft({ ...draft, connector_operation: e.target.value })
                  }
                >
                  <option value="list_issues">List issues</option>
                  <option value="create_issue">Create issue</option>
                </select>
              </label>
              {draft.connector_operation === "create_issue" ? (
                <>
                  <label>
                    Issue title
                    <input
                      required
                      value={draft.parameters?.title ?? ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          parameters: {
                            ...draft.parameters,
                            title: e.target.value,
                          },
                        })
                      }
                    />
                  </label>
                  <label>
                    Issue body
                    <textarea
                      value={draft.parameters?.text ?? ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          parameters: {
                            ...draft.parameters,
                            text: e.target.value,
                          },
                        })
                      }
                    />
                  </label>
                </>
              ) : null}
            </>
          ) : null}
          <label>
            Execution budget in seconds
            <input
              type="number"
              min={30}
              max={900}
              value={draft.timeout_seconds ?? 300}
              onChange={(e) =>
                setDraft({ ...draft, timeout_seconds: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Trigger
            <select
              value={draft.trigger}
              onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}
            >
              {[
                "manual",
                "interval",
                "daily",
                "webhook",
                ...(!draft.group_id ? ["event"] : []),
              ].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          {draft.trigger === "event" ? (
            <label>
              Event
              <select
                value={draft.event ?? "run.completed"}
                onChange={(e) => setDraft({ ...draft, event: e.target.value })}
              >
                <option value="run.completed">User task completed</option>
                <option value="artifact.retained">Agent output retained</option>
              </select>
            </label>
          ) : null}
          {draft.trigger === "daily" ? (
            <>
              <label>
                Timezone
                <input
                  required
                  value={draft.timezone}
                  onChange={(e) =>
                    setDraft({ ...draft, timezone: e.target.value })
                  }
                />
              </label>
              <label>
                Local time
                <input
                  type="time"
                  value={draft.local_time}
                  onChange={(e) =>
                    setDraft({ ...draft, local_time: e.target.value })
                  }
                />
              </label>
              <p>
                Spring-forward missing times are skipped. Repeated fall-back
                times run once, at the first occurrence.
              </p>
            </>
          ) : null}
          {draft.trigger === "interval" ? (
            <label>
              Interval in seconds
              <input
                type="number"
                min={60}
                max={2592000}
                value={draft.interval_seconds}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    interval_seconds: Number(e.target.value),
                  })
                }
              />
            </label>
          ) : null}
          <label>
            Missed schedules
            <select
              value={draft.missed}
              onChange={(e) => setDraft({ ...draft, missed: e.target.value })}
            >
              <option value="skip">Skip missed occurrences</option>
              <option value="latest">Run one latest occurrence</option>
            </select>
          </label>
          <label>
            When the bot is busy
            <select
              value={draft.overlap}
              onChange={(e) => setDraft({ ...draft, overlap: e.target.value })}
            >
              <option value="skip">Skip</option>
              <option value="queue">Queue until budget expires</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.resume_computer}
              onChange={(e) =>
                setDraft({ ...draft, resume_computer: e.target.checked })
              }
            />
            Allow resume of a retained computer
          </label>
          <p>
            Normal approvals and time limits apply. Uncertain or interrupted
            effects are never retried automatically.
          </p>
          <button>Save routine</button>
          <button
            type="button"
            onClick={async () => {
              try {
                const r = await post<{ times: string[] }>(
                  "/api/routines/preview",
                  draft,
                );
                setPreview(r.times);
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            Preview next runs
          </button>
          {preview.map((t) => (
            <p key={t}>{new Date(t).toLocaleString()}</p>
          ))}
        </form>
      </section>
      <section className="center-card">
        <h2>Routines and history</h2>
        {routines.data?.map((r) => (
          <article className="center-message" key={r.id}>
            <strong>{r.definition.name}</strong>
            <p>
              {r.enabled ? "Enabled" : "Paused"} ·{" "}
              {r.next_at
                ? new Date(r.next_at).toLocaleString()
                : r.definition.trigger}
            </p>
            <div className="row">
              <button
                onClick={async () => {
                  try {
                    await post(`/api/routines/${r.id}/run`, {
                      request_id: crypto.randomUUID(),
                    });
                    setHistoryId(r.id);
                    void history.refetch();
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                Run now
              </button>
              <button
                onClick={() => {
                  setDraft({ ...r.definition, version: r.version });
                  setEditing(r.id);
                }}
              >
                Edit
              </button>
              <button
                onClick={async () => {
                  try {
                    await post(
                      `/api/routines/${r.id}`,
                      {
                        ...r.definition,
                        version: r.version,
                        enabled: !r.enabled,
                      },
                      "PATCH",
                    );
                    void routines.refetch();
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                {r.enabled ? "Pause" : "Enable"}
              </button>
              <button onClick={() => setHistoryId(r.id)}>History</button>
              <button
                onClick={async () => {
                  await api(`/api/routines/${r.id}`, { method: "DELETE" });
                  void routines.refetch();
                }}
              >
                Delete
              </button>
            </div>
            {r.definition.trigger === "webhook" ? (
              <button
                onClick={async () => {
                  try {
                    const result = await post<{ secret: string; path: string }>(
                      `/api/routines/${r.id}/webhook-secret`,
                      {},
                    );
                    setSecret(
                      `${apiBase()}${result.path}\nSecret (shown once): ${result.secret}\nSign timestamp.delivery_id.raw_body with HMAC-SHA256. Use X-Agent-Timestamp, X-Agent-Delivery and X-Agent-Signature headers.`,
                    );
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                Rotate webhook secret
              </button>
            ) : null}
          </article>
        ))}
        {secret ? (
          <div>
            <pre>{secret}</pre>
            <button onClick={() => setSecret("")}>Hide secret</button>
          </div>
        ) : null}
        {history.data?.map((j) => (
          <article key={j.id}>
            <strong>{j.state}</strong> ·{" "}
            {new Date(j.created_at).toLocaleString()}
            <p>{j.detail}</p>
            {j.bot_id ? (
              <Link to={`/bots/${j.bot_id}`}>Open run and approvals</Link>
            ) : null}
          </article>
        ))}
      </section>
    </div>
  );
}

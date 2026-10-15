import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Bot } from "../../api/client";
import { post, type Group } from "./workspaceApi";

export function GroupsPanel({
  wid,
  bots,
  onError,
}: {
  wid: string;
  bots: Bot[];
  onError: (s: string) => void;
}) {
  const groups = useQuery({
    queryKey: ["groups", wid],
    queryFn: () => api<Group[]>(`/api/workspaces/${wid}/groups`),
  });
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [gid, setGid] = useState("");
  const [task, setTask] = useState("@group ");
  const [context, setContext] = useState("");
  const detail = useQuery({
    queryKey: ["group", gid],
    queryFn: () =>
      api<{
        messages: { id: string; bot_id: string; content: string }[];
        handoffs: {
          id: string;
          state: string;
          target_bot_id: string;
          source_bot_id: string;
          context: string;
        }[];
      }>(`/api/groups/${gid}`),
    enabled: !!gid,
    refetchInterval: 3000,
  });
  return (
    <div className="center-grid">
      <section className="center-card">
        <h2>Group conversations</h2>
        <p>
          Groups share explicitly attached context. Each bot keeps its own
          computer, credentials, and approvals.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const g = await post<Group>(`/api/workspaces/${wid}/groups`, {
                name,
                bot_ids: members,
              });
              setGid(g.id);
              void groups.refetch();
            } catch (e) {
              onError(String(e));
            }
          }}
        >
          <label>
            Group name
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          {bots.map((b) => (
            <label key={b.id}>
              <input
                type="checkbox"
                checked={members.includes(b.id)}
                onChange={(e) =>
                  setMembers(
                    e.target.checked
                      ? [...members, b.id]
                      : members.filter((id) => id !== b.id),
                  )
                }
              />
              {b.name}
            </label>
          ))}
          <button>Create group</button>
        </form>
        {gid ? (
          <div className="row">
            <button
              onClick={async () => {
                try {
                  await post(
                    `/api/groups/${gid}`,
                    {
                      name,
                      bot_ids: members,
                      revision: groups.data?.find((g) => g.id === gid)
                        ?.revision,
                    },
                    "PATCH",
                  );
                  void groups.refetch();
                  void detail.refetch();
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              Save selected group membership
            </button>
            <button
              onClick={async () => {
                try {
                  await api(`/api/groups/${gid}`, { method: "DELETE" });
                  setGid("");
                  void groups.refetch();
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              Delete selected group and stop its handoffs
            </button>
          </div>
        ) : null}
        {groups.data?.map((g) => (
          <button
            key={g.id}
            onClick={() => {
              setGid(g.id);
              setName(g.name);
              setMembers(g.bot_ids);
            }}
          >
            {g.name}
          </button>
        ))}
      </section>
      {gid ? (
        <section className="center-card">
          <h2>Shared conversation</h2>
          <p>
            Mention @group or a member’s @bot_id to dispatch. Busy bots queue
            until the handoff deadline.
          </p>
          {bots
            .filter((b) =>
              groups.data?.find((g) => g.id === gid)?.bot_ids.includes(b.id),
            )
            .map((b) => (
              <button
                key={b.id}
                onClick={() => setTask((t) => t + ` @${b.id}`)}
              >
                Mention {b.name}
              </button>
            ))}
          {detail.data?.messages.map((m) => (
            <article className="center-message" key={m.id}>
              <strong>
                {bots.find((b) => b.id === m.bot_id)?.name ?? "Operator"}
              </strong>
              <p>{m.content}</p>
            </article>
          ))}
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await post(`/api/groups/${gid}/messages`, {
                  request_id: crypto.randomUUID(),
                  task,
                  context,
                  budget: 4,
                });
                void detail.refetch();
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            <label>
              Task
              <textarea
                required
                value={task}
                onChange={(e) => setTask(e.target.value)}
              />
            </label>
            <label>
              Approved shared context
              <textarea
                value={context}
                onChange={(e) => setContext(e.target.value)}
              />
            </label>
            <button>Send group task</button>
          </form>
          {detail.data?.handoffs.map((h) => (
            <details key={h.id}>
              <summary>
                {h.source_bot_id
                  ? `${bots.find((b) => b.id === h.source_bot_id)?.name ?? h.source_bot_id} → `
                  : ""}
                {bots.find((b) => b.id === h.target_bot_id)?.name ??
                  h.target_bot_id}{" "}
                · {h.state}
              </summary>
              <pre>{h.context}</pre>
              <Link to={`/bots/${h.target_bot_id}`}>
                Open bot and approvals
              </Link>
              {["running", "accepted"].includes(h.state) ? (
                <button
                  onClick={async () => {
                    await api(`/api/groups/${gid}/handoffs/${h.id}`, {
                      method: "DELETE",
                    });
                    void detail.refetch();
                  }}
                >
                  Cancel handoff
                </button>
              ) : null}
            </details>
          ))}
        </section>
      ) : null}
    </div>
  );
}

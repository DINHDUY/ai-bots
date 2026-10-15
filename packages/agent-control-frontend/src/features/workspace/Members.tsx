import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { post } from "./workspaceApi";

export function Members({
  wid,
  bid,
  owner,
  onError,
}: {
  wid: string;
  bid: string;
  owner: boolean;
  onError: (s: string) => void;
}) {
  const members = useQuery({
    queryKey: ["members", wid],
    queryFn: () =>
      api<{ user_id: string; username: string; role: string }[]>(
        `/api/workspaces/${wid}/members`,
      ),
    enabled: owner,
  });
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("viewer");
  const [execution, setExecution] = useState(false);
  const [surfaces, setSurfaces] = useState<string[]>([]);
  const [artifacts, setArtifacts] = useState("");
  const [share, setShare] = useState<{ id: string; url: string }>();
  return (
    <div className="center-grid">
      <section className="center-card">
        <h2>Workspace members</h2>
        <p>
          Viewers can inspect workspace data. Operators need a separate bot
          execution grant to run, approve, or control a computer.
        </p>
        {members.data?.map((m) => (
          <div className="center-line" key={m.user_id}>
            <span>
              {m.username} · {m.role}
            </span>
            {m.role !== "owner" ? (
              <button
                onClick={async () => {
                  try {
                    await post(`/api/workspaces/${wid}/members`, {
                      username: m.username,
                      role: "remove",
                    });
                    void members.refetch();
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                Remove
              </button>
            ) : null}
          </div>
        ))}
        {owner ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await post(`/api/workspaces/${wid}/members`, {
                  username,
                  role,
                });
                if (execution && bid && role === "operator")
                  await post(`/api/bots/${bid}/execution-grants`, {
                    username,
                    enabled: true,
                  });
                void members.refetch();
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            <label>
              Registered username
              <input
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label>
              Role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="viewer">Viewer</option>
                <option value="operator">Operator</option>
              </select>
            </label>
            {role === "operator" ? (
              <label>
                <input
                  type="checkbox"
                  checked={execution}
                  onChange={(e) => setExecution(e.target.checked)}
                />
                Authorize use of the selected bot’s credentials for execution
              </label>
            ) : null}
            <button>Add or update member</button>
          </form>
        ) : (
          <p>Only the owner manages members.</p>
        )}
        {owner && bid ? (
          <button
            onClick={async () => {
              try {
                await post(`/api/bots/${bid}/execution-grants`, {
                  username,
                  enabled: false,
                });
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            Revoke selected user’s bot execution grant
          </button>
        ) : null}
      </section>
      {owner && bid ? (
        <section className="center-card">
          <h2>Share selected content</h2>
          <p>
            Only the named signed-in recipient can open this share. Sharing a
            live surface exposes everything visible on it. No surface is
            selected by default.
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const report = await api<{ computer: { id: string } | null }>(
                  `/api/bots/${bid}/computer`,
                );
                setShare(
                  await post(`/api/bots/${bid}/shares`, {
                    username,
                    session_id: report.computer?.id ?? null,
                    surfaces,
                    artifacts: artifacts
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                    hours: 24,
                  }),
                );
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            <label>
              Recipient username
              <input
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            {["browser", "desktop"].map((surface) => (
              <label key={surface}>
                <input
                  type="checkbox"
                  checked={surfaces.includes(surface)}
                  onChange={(e) =>
                    setSurfaces(
                      e.target.checked
                        ? [...surfaces, surface]
                        : surfaces.filter((s) => s !== surface),
                    )
                  }
                />
                Live {surface}
              </label>
            ))}
            <label>
              Retained artifact IDs, separated by commas
              <input
                value={artifacts}
                onChange={(e) => setArtifacts(e.target.value)}
              />
            </label>
            <button>Create 24-hour share</button>
          </form>
          {share ? (
            <div>
              <Link to={share.url.replace("/#", "")}>Open recipient link</Link>
              <code>
                {location.origin}
                {location.pathname}
                {share.url.slice(1)}
              </code>
              <button
                onClick={async () => {
                  await api(`/api/bots/${bid}/shares/${share.id}`, {
                    method: "DELETE",
                  });
                  setShare(undefined);
                }}
              >
                Revoke share
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

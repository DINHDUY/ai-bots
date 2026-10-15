import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useHumanControl, leaseBody } from "../../session/humanControl";
import { type ToolkitData, post } from "./workspaceApi";

type Step = {
  operation: string;
  surface?: string;
  input?: { kind: string; key?: string; text?: string };
  width?: number;
  height?: number;
  url?: string;
  selector?: string;
  text?: string;
};
export function ToolkitPanel({
  bid,
  onError,
}: {
  bid: string;
  onError: (s: string) => void;
}) {
  const toolkit = useQuery({
    queryKey: ["toolkit", bid],
    queryFn: () => api<ToolkitData>(`/api/bots/${bid}/toolkit`),
    refetchInterval: 3000,
  });
  const lease = useHumanControl((s) => s.bots[bid]?.lease);
  const [name, setName] = useState("");
  const [recordingId, setRecordingId] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [parameters, setParameters] = useState("");
  const [values, setValues] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [title, setTitle] = useState("");
  async function recording(operation: string) {
    if (!lease) return;
    try {
      await post(`/api/bots/${bid}/sessions/${lease.session_id}/recordings`, {
        ...leaseBody(lease),
        operation,
      });
      void toolkit.refetch();
    } catch (e) {
      onError(String(e));
    }
  }
  const active = toolkit.data?.recordings.find((r) => r.state !== "stopped");
  const params = () =>
    Object.fromEntries(
      values
        .split("\n")
        .filter((s) => s.includes("="))
        .map((s) => [s.slice(0, s.indexOf("=")), s.slice(s.indexOf("=") + 1)]),
    );
  return (
    <div className="center-grid">
      <section className="center-card">
        <h2>Teach a task</h2>
        <p>
          Take human control from the computer panel, then start recording.
          Private mode omits input payloads and captures. Recorded coordinate
          steps are fragile and require the same viewport and page.
        </p>
        {active ? (
          <p role="status">
            <strong>
              {active.private
                ? "Private input — no payloads or captures saved"
                : `Recording ${active.state}`}
            </strong>
          </p>
        ) : null}
        <div className="row">
          {["start", "pause", "resume", "stop", "private", "public"].map(
            (op) => (
              <button
                key={op}
                disabled={!lease}
                onClick={() => void recording(op)}
              >
                {op === "private"
                  ? "Private input"
                  : op === "public"
                    ? "Record input"
                    : op[0].toUpperCase() + op.slice(1)}
              </button>
            ),
          )}
        </div>
        {toolkit.data?.recordings
          .filter((r) => r.state === "stopped")
          .map((r) => (
            <button
              key={r.id}
              onClick={() => {
                setRecordingId(r.id);
                setSteps(JSON.parse(r.steps));
              }}
            >
              Review recording {r.id.slice(-6)}
            </button>
          ))}
        {recordingId ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const schema = Object.fromEntries(
                  parameters
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean)
                    .map((s) => [s, "string"]),
                );
                await post(`/api/bots/${bid}/skills`, {
                  name,
                  recording_id: recordingId,
                  parameters: schema,
                  steps,
                });
                setRecordingId("");
                void toolkit.refetch();
              } catch (e) {
                onError(String(e));
              }
            }}
          >
            <label>
              Skill name
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Parameter names, separated by commas
              <input
                value={parameters}
                onChange={(e) => setParameters(e.target.value)}
              />
            </label>
            <p>
              Replace a reviewed text value with {"{{parameter}}"}. Remove
              sensitive or unsupported steps before saving.
            </p>
            {steps.map((s, i) => (
              <div className="center-message" key={i}>
                <strong>
                  {i + 1}. {s.operation} {s.input?.kind}
                </strong>
                <pre>{JSON.stringify(s)}</pre>
                {s.input?.kind === "text" ? (
                  <input
                    aria-label={`Step ${i + 1} text`}
                    value={s.input.text ?? ""}
                    onChange={(e) =>
                      setSteps(
                        steps.map((v, j) =>
                          j === i
                            ? {
                                ...v,
                                input: { ...v.input!, text: e.target.value },
                              }
                            : v,
                        ),
                      )
                    }
                  />
                ) : null}
                <button
                  type="button"
                  onClick={() => setSteps(steps.filter((_, j) => j !== i))}
                >
                  Remove step
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => {
                const previous = steps.find((s) => s.surface);
                setSteps([
                  ...steps,
                  {
                    operation: "input",
                    surface: previous?.surface ?? "browser",
                    width: previous?.width ?? 1024,
                    height: previous?.height ?? 768,
                    url: previous?.url,
                    input: { kind: "text", text: "{{value}}" },
                  },
                ]);
              }}
            >
              Add parameterized text input
            </button>
            <button>Save immutable skill and install</button>
          </form>
        ) : null}
      </section>
      <section className="center-card">
        <h2>Installed skills</h2>
        <label>
          Replay values, one name=value per line
          <textarea
            value={values}
            onChange={(e) => setValues(e.target.value)}
          />
        </label>
        {toolkit.data?.skills.map((s) => (
          <article key={s.id}>
            <strong>{s.name}</strong>
            {!s.installed ? (
              <button
                onClick={async () => {
                  try {
                    await post(`/api/bots/${bid}/toolkit/skill/${s.id}`, {});
                    void toolkit.refetch();
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                Install version on this bot
              </button>
            ) : null}
            <p>
              Parameters:{" "}
              {Object.keys(JSON.parse(s.parameters)).join(", ") || "none"}
            </p>
            <button
              disabled={!s.installed}
              onClick={async () => {
                try {
                  await post(`/api/bots/${bid}/skills/${s.id}/replay`, {
                    request_id: crypto.randomUUID(),
                    parameters: params(),
                    resume_paused: true,
                  });
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              Resume and replay with approvals
            </button>
            <button
              onClick={async () => {
                await api(`/api/bots/${bid}/toolkit/skill/${s.id}`, {
                  method: "DELETE",
                });
                void toolkit.refetch();
              }}
            >
              Uninstall
            </button>
          </article>
        ))}
        <h2>GitHub repository issues</h2>
        <p>
          Use a fine-grained personal access token restricted to one repository
          with metadata read and issues read/write. Credentials stay in the
          backend connector runner.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await post(`/api/bots/${bid}/connections/github`, {
                repository: repo,
                token,
              });
              setToken("");
              void toolkit.refetch();
            } catch (e) {
              onError(String(e));
            }
          }}
        >
          <label>
            Repository
            <input
              required
              placeholder="owner/repository"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
            />
          </label>
          <label>
            Token
            <input
              type="password"
              required
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <button>Connect and check access</button>
        </form>
        <label>
          New issue title
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        {toolkit.data?.connections.map((c) => (
          <article key={c.id}>
            <strong>{c.repository}</strong>
            <button
              disabled={!token || c.status === "revoked"}
              onClick={async () => {
                try {
                  await post(`/api/bots/${bid}/connections/${c.id}/rotate`, {
                    repository: repo || c.repository,
                    token,
                  });
                  setToken("");
                  void toolkit.refetch();
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              Rotate connection using entered token
            </button>
            <p>{c.status}</p>
            <button
              onClick={async () => {
                try {
                  await post(`/api/bots/${bid}/connections/${c.id}/health`, {});
                  void toolkit.refetch();
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              Check connection
            </button>
            {["list_issues", "create_issue"].map((op) => (
              <button
                key={op}
                disabled={c.status === "revoked"}
                onClick={async () => {
                  try {
                    await post(`/api/bots/${bid}/connections/${c.id}/invoke`, {
                      request_id: crypto.randomUUID(),
                      operation: op,
                      title,
                    });
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                {op === "list_issues" ? "List issues" : "Create issue"}
              </button>
            ))}
            <button
              onClick={async () => {
                await api(`/api/bots/${bid}/toolkit/connector/${c.id}`, {
                  method: "DELETE",
                });
                void toolkit.refetch();
              }}
            >
              Revoke locally and uninstall
            </button>
          </article>
        ))}
        <Link to={`/bots/${bid}`}>
          Open bot to review approvals and results
        </Link>
      </section>
    </div>
  );
}

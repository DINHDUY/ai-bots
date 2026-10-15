import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Credential } from "../../api/client";
import styles from "../bots/dialog.module.css";
import pageStyles from "./keys.module.css";

export function KeysPage() {
  const queryClient = useQueryClient();
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<Credential[]>("/api/credentials"),
  });
  const [provider, setProvider] = useState("openai");
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: (body: {
      provider: string;
      label: string;
      api_key: string;
      endpoint: string;
    }) =>
      api<Credential>("/api/credentials", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) =>
      api<{ status: string }>(`/api/credentials/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await create.mutateAsync({
        provider,
        label: String(data.get("label") ?? ""),
        api_key: String(data.get("api_key") ?? ""),
        endpoint:
          provider === "azure_foundry"
            ? String(data.get("endpoint") ?? "")
            : "",
      });
      form.reset();
      setProvider("openai");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    }
  }

  const list = credentials.data ?? [];

  return (
    <div className={`${styles.dialog} ${pageStyles.card}`}>
      <h2>API keys</h2>
      <p>Keys stay on your account. Bots choose one when they run.</p>
      {credentials.isPending ? <p>Loading…</p> : null}
      {credentials.isError ? (
        <p className="error" role="alert">
          Could not load your API keys.{" "}
          <button onClick={() => void credentials.refetch()}>Try again</button>
        </p>
      ) : null}
      {list.length === 0 && !credentials.isPending ? <p>No keys yet.</p> : null}
      <ul>
        {list.map((item) => (
          <li key={item.id}>
            <strong>{item.label}</strong> · {item.provider}
            {item.endpoint ? ` · ${item.endpoint}` : ""} · ••••{item.key_hint}{" "}
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Delete ${item.label}?`)) {
                  remove.mutate(item.id, {
                    onError: (caught) =>
                      setError(
                        caught instanceof Error
                          ? caught.message
                          : "Request failed",
                      ),
                  });
                }
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: "0.75rem" }}>
        <label>
          Provider
          <select
            name="provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="azure_foundry">Azure Foundry (xAI)</option>
          </select>
        </label>
        <label>
          Label
          <input name="label" required />
        </label>
        <label>
          API key
          <input name="api_key" type="password" required autoComplete="off" />
        </label>
        {provider === "azure_foundry" ? (
          <label>
            Endpoint
            <input
              name="endpoint"
              required
              placeholder="https://example.services.ai.azure.com/openai/v1"
            />
          </label>
        ) : null}
        <p className="error">{error}</p>
        <div className={styles.actions}>
          <button className="primary" type="submit">
            Add key
          </button>
        </div>
      </form>
    </div>
  );
}

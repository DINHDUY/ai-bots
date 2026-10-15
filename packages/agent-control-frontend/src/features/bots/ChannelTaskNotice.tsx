import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { channelState } from "../workspace/channel";
import "../workspace/channel.css";

export function ChannelTaskNotice({ botId }: { botId: string }) {
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () =>
      api<{ workspace_bot_channels?: boolean }>("/api/capabilities"),
  });
  const task = useQuery({
    queryKey: ["channel-task", botId],
    queryFn: () =>
      api<{
        thread_id: string;
        workspace_id: string;
        state: string;
        wait_state: string;
        wait_mode: string;
      } | null>(`/api/bots/${botId}/collaboration-task`),
    enabled: !!capabilities.data?.workspace_bot_channels,
    refetchInterval: 1500,
  });
  const [error, setError] = useState("");
  const value = task.data;
  if (!value || value.state === "resolved" || value.wait_state === "resumed")
    return null;
  const waiting =
    ["waiting", "queued"].includes(value.wait_state) &&
    ["open", "waiting_peer"].includes(value.state);
  return (
    <div className="channel-waiting" role="status">
      <span>
        {waiting
          ? value.wait_mode === "computer"
            ? "Waiting for computer tools"
            : "Waiting for a peer reply"
          : `Collaboration ${channelState(value.state).toLowerCase()}`}
      </span>
      <Link
        to={`/channel?workspace=${value.workspace_id}&thread=${value.thread_id}`}
      >
        View thread
      </Link>
      {waiting ? (
        <button
          type="button"
          onClick={async () => {
            try {
              await api(
                `/api/workspaces/${value.workspace_id}/channel/threads/${value.thread_id}/cancel`,
                { method: "POST" },
              );
              await task.refetch();
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          Stop task
        </button>
      ) : null}
      {error ? <span role="alert">{error}</span> : null}
    </div>
  );
}

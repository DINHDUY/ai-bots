import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { post } from "./workspaceApi";

export function Notifications() {
  const items = useQuery({
    queryKey: ["notification-history"],
    queryFn: () =>
      api<
        {
          id: string;
          kind: string;
          url: string;
          read: number;
          created_at: string;
        }[]
      >("/api/notifications"),
    refetchInterval: 10000,
  });
  return (
    <section className="center-card">
      <h2>Notification history</h2>
      {items.data?.length === 0 ? <p>No notifications yet.</p> : null}
      {items.data?.map((n) => (
        <div className="center-line" key={n.id}>
          <Link to={n.url.replace("/#", "")}>
            {n.kind} · {new Date(n.created_at).toLocaleString()}
          </Link>
          <button
            disabled={!!n.read}
            onClick={async () => {
              await post(`/api/notifications/${n.id}/read`, {});
              void items.refetch();
            }}
          >
            {n.read ? "Read" : "Mark read"}
          </button>
        </div>
      ))}
    </section>
  );
}

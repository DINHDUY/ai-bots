import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

export function SearchPanel({ wid }: { wid: string }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [cursor, setCursor] = useState(0);
  const results = useQuery({
    queryKey: ["search", wid, query, kind, cursor],
    queryFn: () =>
      api<{
        hits: {
          resource_id: string;
          bot_id: string;
          title: string;
          snippet: string;
          kind: string;
        }[];
        next_cursor: number | null;
      }>(
        `/api/workspaces/${wid}/search?q=${encodeURIComponent(query)}&kind=${kind}&cursor=${cursor}`,
      ),
    enabled: !!query,
  });
  return (
    <section className="center-card">
      <h2>Search this workspace</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setCursor(0);
          setQuery(q);
        }}
      >
        <label>
          Search
          <input required value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <select
          aria-label="Search type"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setCursor(0);
          }}
        >
          {["all", "bot", "message", "skill", "routine", "file"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <button>Search</button>
      </form>
      {results.error ? <p role="alert">{String(results.error)}</p> : null}
      {results.data?.hits.map((h) => (
        <article key={`${h.kind}:${h.resource_id}`}>
          <Link to={`/bots/${h.bot_id}`}>{h.title}</Link>
          <p>{h.snippet}</p>
        </article>
      ))}
      {results.data?.next_cursor != null ? (
        <button onClick={() => setCursor(results.data!.next_cursor!)}>
          Next page
        </button>
      ) : null}
    </section>
  );
}

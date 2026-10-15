import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import "./retention.css";

type Policy = {
  revision: number;
  max_count: number | null;
  max_bytes: number | null;
  max_age_seconds: number | null;
  reserve_percent: number;
  cleanup_target_percent: number;
};
type Settings = Policy & {
  role: string;
  shared_limit_bytes: number;
  cleanup_pending: boolean;
  last_cleanup_at: string | null;
  last_error: string | null;
  usage: {
    retained_count: number;
    screenshot_bytes: number;
    pending_bytes: number;
    shared_bytes: number;
  };
};
const MiB = 1024 ** 2;
const GiB = 1024 ** 3;
const size = (bytes: number) =>
  bytes >= GiB
    ? `${(bytes / GiB).toFixed(2)} GiB`
    : `${(bytes / MiB).toFixed(2)} MiB`;
function policy(value: Settings): Policy {
  return {
    revision: value.revision,
    max_count: value.max_count,
    max_bytes: value.max_bytes,
    max_age_seconds: value.max_age_seconds,
    reserve_percent: value.reserve_percent,
    cleanup_target_percent: value.cleanup_target_percent,
  };
}
export function CaptureRetentionSettings({ wid }: { wid: string }) {
  const url = `/api/workspaces/${wid}/capture-retention`;
  const query = useQuery({
    queryKey: ["capture-retention", wid],
    queryFn: () => api<Settings>(url),
    refetchInterval: 5000,
  });
  const [draft, setDraft] = useState<Policy | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [unit, setUnit] = useState(GiB);
  const [customAge, setCustomAge] = useState(false);
  const value = draft ?? (query.data ? policy(query.data) : null);
  const validation = !value
    ? ""
    : [
          value.max_count,
          value.max_bytes,
          value.max_age_seconds,
          value.reserve_percent,
          value.cleanup_target_percent,
        ].some((n) => n !== null && (!Number.isSafeInteger(n) || n <= 0))
      ? "Enter positive whole numbers for enabled limits."
      : [value.max_count, value.max_bytes, value.max_age_seconds].every(
            (n) => n === null,
          )
        ? "Enable at least one retention limit."
        : value.max_bytes !== null &&
            value.max_bytes > (query.data?.shared_limit_bytes ?? 0)
          ? "Maximum screenshot size exceeds the shared workspace ceiling. Increase WORKSPACE_BLOB_LIMIT_BYTES on the server first."
          : value.max_bytes !== null &&
              (value.cleanup_target_percent >= 100 - value.reserve_percent ||
                (value.max_bytes * value.cleanup_target_percent) / 100 <
                  4 * MiB)
            ? "Set a cleanup target below the trigger with room for a 4 MiB screenshot."
            : "";
  const encoded = value ? JSON.stringify(value) : "";
  const [preview, setPreview] = useState<{
    key: string;
    remove_count: number;
    remove_bytes: number;
  } | null>(null);
  const owner = query.data?.role === "owner";
  useEffect(() => {
    setPreview(null);
    if (!encoded || !owner || validation) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      void api<{ remove_count: number; remove_bytes: number }>(
        `${url}/preview`,
        { method: "POST", body: encoded, signal: abort.signal },
      )
        .then((result) => {
          if (!abort.signal.aborted) {
            setPreview({ key: encoded, ...result });
            setError("");
          }
        })
        .catch((e) => {
          if (!abort.signal.aborted) setError(String(e));
        });
    }, 350);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [encoded, url, owner, validation]);
  if (query.isError)
    return (
      <p role="alert">
        Screenshot retention settings could not be loaded.{" "}
        <button onClick={() => void query.refetch()}>Retry</button>
      </p>
    );
  if (!query.data || !value) return <p>Loading screenshot retention…</p>;
  const data = query.data;
  function change(patch: Partial<Policy>) {
    setDraft({ ...value!, ...patch });
    setError("");
    setSaved(false);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (validation || preview?.key !== encoded) return;
    setBusy(true);
    setError("");
    try {
      await api<Settings>(url, { method: "PATCH", body: encoded });
      await query.refetch();
      setDraft(null);
      setSaved(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="center-card retention-settings" onSubmit={save}>
      <h2>Screenshot retention</h2>
      <p>
        Applies to all bots and screen surfaces in this workspace. Enabled
        limits work together; oldest screenshots are deleted first.
      </p>
      <p className="muted">
        {data.usage.retained_count} screenshots ·{" "}
        {size(data.usage.screenshot_bytes)} stored ·{" "}
        {size(data.usage.pending_bytes)} pending deletion
      </p>
      <p className="muted">
        Shared storage: {size(data.usage.shared_bytes)} of{" "}
        {size(data.shared_limit_bytes)}. Retained files share this space and may
        cause earlier screenshot cleanup.
      </p>
      <fieldset disabled={!owner || busy} className="retention-limits">
        <div>
          <label className="retention-toggle">
            <input
              type="checkbox"
              checked={value.max_count !== null}
              onChange={(e) =>
                change({ max_count: e.target.checked ? 1000 : null })
              }
            />
            <span>Keep latest screenshots</span>
          </label>
          {value.max_count !== null ? (
            <label>
              Maximum screenshots
              <input
                type="number"
                min={1}
                max={1000000}
                required
                value={Number.isFinite(value.max_count) ? value.max_count : ""}
                onChange={(e) => change({ max_count: e.target.valueAsNumber })}
              />
            </label>
          ) : null}
        </div>
        <div>
          <label className="retention-toggle">
            <input
              type="checkbox"
              checked={value.max_bytes !== null}
              onChange={(e) =>
                change({
                  max_bytes: e.target.checked
                    ? Math.min(GiB, data.shared_limit_bytes)
                    : null,
                })
              }
            />
            <span>Limit screenshot storage</span>
          </label>
          {value.max_bytes !== null ? (
            <>
              <div className="retention-size">
                <label>
                  Maximum size
                  <input
                    type="number"
                    min={0.001}
                    step="any"
                    required
                    value={
                      Number.isFinite(value.max_bytes)
                        ? value.max_bytes / unit
                        : ""
                    }
                    onChange={(e) =>
                      change({
                        max_bytes: Math.round(e.target.valueAsNumber * unit),
                      })
                    }
                  />
                </label>
                <label>
                  Unit
                  <select
                    value={unit}
                    onChange={(e) => setUnit(Number(e.target.value))}
                  >
                    <option value={GiB}>GiB</option>
                    <option value={MiB}>MiB</option>
                  </select>
                </label>
              </div>
              <label>
                Reserve (%)
                <input
                  type="number"
                  min={1}
                  max={98}
                  value={value.reserve_percent}
                  onChange={(e) =>
                    change({ reserve_percent: e.target.valueAsNumber })
                  }
                  required
                />
              </label>
              <label>
                Clean down to (%)
                <input
                  type="number"
                  min={1}
                  max={98}
                  value={value.cleanup_target_percent}
                  onChange={(e) =>
                    change({ cleanup_target_percent: e.target.valueAsNumber })
                  }
                  required
                />
              </label>
              <p>
                At {100 - value.reserve_percent}% (
                {size((value.max_bytes * (100 - value.reserve_percent)) / 100)}
                ), delete oldest screenshots down to{" "}
                {value.cleanup_target_percent}% (
                {size((value.max_bytes * value.cleanup_target_percent) / 100)}).
              </p>
            </>
          ) : null}
        </div>
        <div>
          <label className="retention-toggle">
            <input
              type="checkbox"
              checked={value.max_age_seconds !== null}
              onChange={(e) =>
                change({ max_age_seconds: e.target.checked ? 604800 : null })
              }
            />
            <span>Delete screenshots older than</span>
          </label>
          {value.max_age_seconds !== null ? (
            <>
              <label>
                Retention period
                <select
                  value={
                    customAge ||
                    ![86400, 604800].includes(value.max_age_seconds)
                      ? "custom"
                      : value.max_age_seconds
                  }
                  onChange={(e) => {
                    setCustomAge(e.target.value === "custom");
                    if (e.target.value !== "custom")
                      change({ max_age_seconds: Number(e.target.value) });
                  }}
                >
                  <option value={86400}>1 day</option>
                  <option value={604800}>1 week</option>
                  <option value="custom">Custom hours</option>
                </select>
              </label>
              {customAge || ![86400, 604800].includes(value.max_age_seconds) ? (
                <label>
                  Hours
                  <input
                    type="number"
                    min={1}
                    max={87600}
                    required
                    value={
                      Number.isFinite(value.max_age_seconds)
                        ? value.max_age_seconds / 3600
                        : ""
                    }
                    onChange={(e) =>
                      change({ max_age_seconds: e.target.valueAsNumber * 3600 })
                    }
                  />
                </label>
              ) : null}
              <p>Rolling age from capture time; one day is 24 hours.</p>
            </>
          ) : null}
        </div>
      </fieldset>
      {owner ? (
        <>
          <p>
            Saving applies these limits to existing screenshots. Deleted
            screenshots cannot be restored.
          </p>
          <p role="status">
            {preview?.key === encoded
              ? `Estimated cleanup: ${preview.remove_count} screenshots (${size(preview.remove_bytes)}).`
              : "Checking policy…"}
          </p>
        </>
      ) : (
        <p>Only a workspace owner can change retention.</p>
      )}
      {validation ? <p role="alert">{validation}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {data.last_error ? (
        <p role="alert">{data.last_error} Cleanup will retry.</p>
      ) : null}
      <p role="status">
        {data.cleanup_pending
          ? "Cleanup pending"
          : saved
            ? "Retention settings saved"
            : "Policy active"}
        {data.last_cleanup_at
          ? ` · Last cleanup ${new Date(data.last_cleanup_at).toLocaleString()}`
          : ""}
      </p>
      {owner ? (
        <div className="retention-actions">
          <button
            className="primary"
            disabled={
              busy || !draft || !!validation || preview?.key !== encoded
            }
          >
            Save
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setDraft(null);
              setError("");
              setSaved(false);
              void query.refetch();
            }}
          >
            Cancel / reload
          </button>
        </div>
      ) : null}
    </form>
  );
}

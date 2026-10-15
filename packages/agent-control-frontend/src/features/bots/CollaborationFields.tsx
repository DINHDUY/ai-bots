import type { Collaboration, CollaborationDraft } from "../workspace/channel";
import "../workspace/channel.css";

export function CollaborationFields({
  saved,
  draft,
  onChange,
  disabled,
}: {
  saved: Collaboration;
  draft: CollaborationDraft | null;
  onChange: (value: CollaborationDraft) => void;
  disabled: boolean;
}) {
  const value = draft ?? {
    revision: saved.revision,
    enabled: saved.state === "enabled",
    purpose: saved.purpose,
    expires_at: saved.expires_at,
  };
  return (
    <section className="channel-settings" aria-label="Bot collaboration">
      <h3>Workspace collaboration</h3>
      <label className="channel-check">
        <input
          type="checkbox"
          checked={value.enabled}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, enabled: e.target.checked })}
        />
        Join workspace channel
      </label>
      <p>
        Publish this bot's name and purpose so peers can request help. Adds the
        Bot channel tool. Workspace collaboration must also be enabled.
      </p>
      <label>
        Public purpose
        <input
          maxLength={400}
          value={value.purpose}
          disabled={disabled}
          placeholder="What can this bot help with?"
          onChange={(e) => onChange({ ...value, purpose: e.target.value })}
        />
      </label>
      <label>
        Participation expiry (optional)
        <input
          type="datetime-local"
          value={value.expires_at ? localDate(value.expires_at) : ""}
          disabled={disabled}
          onChange={(e) =>
            onChange({
              ...value,
              expires_at: e.target.value
                ? new Date(e.target.value).toISOString()
                : null,
            })
          }
        />
      </label>
      <small>
        Visible to workspace members. Keep private instructions and credentials
        out of the public purpose.
      </small>
    </section>
  );
}

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

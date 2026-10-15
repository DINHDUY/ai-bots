import { useState } from "react";
import { post, type Preferences } from "./workspaceApi";

export function Profile({
  preferences,
  onSaved,
  onError,
}: {
  preferences: Preferences;
  onSaved: () => void;
  onError: (s: string) => void;
}) {
  const [draft, setDraft] = useState(preferences);
  return (
    <form
      className="center-card"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await post("/api/preferences", draft);
          onSaved();
        } catch (e) {
          onError(String(e));
        }
      }}
    >
      <h2>Profile and sidebar</h2>
      <label>
        Avatar or icon name
        <input
          value={draft.avatar}
          onChange={(e) => setDraft({ ...draft, avatar: e.target.value })}
        />
      </label>
      <label>
        Display role
        <input
          value={draft.display_role}
          onChange={(e) => setDraft({ ...draft, display_role: e.target.value })}
        />
      </label>
      <label>
        Sidebar bot order, one bot ID per line
        <textarea
          value={draft.order.join("\n")}
          onChange={(e) =>
            setDraft({
              ...draft,
              order: e.target.value.split("\n").filter(Boolean),
            })
          }
        />
      </label>
      <label>
        Sidebar folders, one bot_id=folder per line
        <textarea
          value={Object.entries(draft.folders)
            .map(([id, folder]) => `${id}=${folder}`)
            .join("\n")}
          onChange={(e) =>
            setDraft({
              ...draft,
              folders: Object.fromEntries(
                e.target.value
                  .split("\n")
                  .filter((s) => s.includes("="))
                  .map((s) => [
                    s.slice(0, s.indexOf("=")),
                    s.slice(s.indexOf("=") + 1),
                  ]),
              ),
            })
          }
        />
      </label>
      <button>Save preferences</button>
    </form>
  );
}

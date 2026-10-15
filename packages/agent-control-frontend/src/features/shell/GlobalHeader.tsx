import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Bot, type User } from "../../api/client";
import { Avatar } from "../../components/ui/Avatar";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { Icon } from "../../components/ui/Icon";
import { pendingApprovals } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { readPreference, savePreference } from "../../session/workspaceUiStore";
import styles from "./shell.module.css";

type Props = {
  user: User;
  bots: Bot[];
  search: string;
  onSearch: (value: string) => void;
  onCreate: () => void;
  account: boolean;
  onAccount: (open: boolean) => void;
  onSignOut: () => Promise<void>;
};
export function GlobalHeader({
  user,
  bots,
  search,
  onSearch,
  onCreate,
  account,
  onAccount,
  onSignOut,
}: Props) {
  const sessions = useSessionStore((state) => state.sessions);
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<{ workspaces: boolean }>("/api/capabilities"),
    staleTime: 60000,
    retry: false,
  });
  const profile = useQuery({
    queryKey: ["preferences"],
    queryFn: () =>
      api<{ avatar: string; display_role: string }>("/api/preferences"),
  });
  const waiting = bots.flatMap((bot) =>
    (sessions[bot.id] ? pendingApprovals(sessions[bot.id]) : []).map(
      (item) => ({ bot, item }),
    ),
  );
  const [notifications, setNotifications] = useState(false);
  const [theme, setTheme] = useState(() =>
    readPreference("theme", "dark") === "light" ? "light" : "dark",
  );
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    savePreference("theme", theme);
  }, [theme]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  return (
    <header className={styles.global}>
      <a
        className={styles.skip}
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <Link className={styles.brand} to="/overview">
        <svg viewBox="0 0 30 30" aria-hidden="true">
          <path d="m4 24 10-19h5L9 24H4Zm9 0 6-12 7 12h-6l-3-5" />
        </svg>
        Agent Control
      </Link>
      {capabilities.data?.workspaces ? (
        <Link to="/workspace" className={styles.workspaceLabel}>
          <Icon name="grid" />
          Workspace settings
        </Link>
      ) : null}
      <label className={styles.search}>
        <Icon name="search" />
        <input
          ref={input}
          aria-label="Search bots"
          placeholder="Search bots…"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        <kbd>Ctrl K</kbd>
      </label>
      <span className="spacer" />
      <Button className={styles.newBot} onClick={onCreate} aria-label="New bot">
        <Icon name="plus" />
        <span>New bot</span>
      </Button>
      <button
        className={`icon-button ghost ${styles.bell}`}
        aria-label={`Notifications, ${waiting.length} pending approvals`}
        onClick={() => setNotifications(true)}
      >
        <Icon name="bell" />
        {waiting.length > 0 ? <i /> : null}
      </button>
      <button
        className={`ghost ${styles.user}`}
        aria-label="Account menu"
        onClick={() => onAccount(true)}
      >
        <Avatar
          name={profile.data?.avatar || user.username}
          id={user.id}
          person
        />
        {profile.data?.display_role ? (
          <span>{profile.data.display_role}</span>
        ) : null}
        <span>{user.username}</span>
      </button>
      <Dialog
        open={notifications}
        title="Pending approvals"
        onClose={() => setNotifications(false)}
      >
        {capabilities.data?.workspaces ? (
          <p>
            <Link
              to="/workspace?tab=notifications"
              onClick={() => setNotifications(false)}
            >
              Open notification history
            </Link>
          </p>
        ) : null}
        {waiting.length === 0 ? (
          <p className="muted">
            You’re all caught up. New approvals will appear here.
          </p>
        ) : (
          <ul className={styles.notificationList}>
            {waiting.map(({ bot, item }) => (
              <li key={`${bot.id}:${item.approvalId}`}>
                <Link
                  to={`/bots/${bot.id}`}
                  onClick={() => setNotifications(false)}
                >
                  <strong>{bot.name}</strong>
                  <span>{item.action} · Review in conversation</span>
                  <Icon name="arrow" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
      <Dialog
        open={account}
        title="My account"
        onClose={() => onAccount(false)}
      >
        <div className={styles.account}>
          <div className="row">
            <Avatar name={user.username} id={user.id} person />
            <h3>{user.username}</h3>
          </div>
          <Link to="/keys" onClick={() => onAccount(false)}>
            <Icon name="lock" />
            API keys
            <Icon name="arrow" />
          </Link>
          <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          <p className="error" role="status">
            {error}
          </p>
          <button
            onClick={async () => {
              try {
                await onSignOut();
              } catch {
                setError("Could not sign out. Please try again.");
              }
            }}
          >
            Sign out
          </button>
        </div>
      </Dialog>
    </header>
  );
}

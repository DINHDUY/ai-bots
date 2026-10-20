import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useMatch,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { api, ApiError, type Bot, type User } from "../../api/client";
import { Icon } from "../../components/ui/Icon";
import { EmptyState } from "../../components/ui/EmptyState";
import { Sidebar } from "../bots/Sidebar";
import { BotWorkspace } from "../bots/BotWorkspace";
import { CreateBotDialog } from "../bots/CreateBotDialog";
import { KeysPage } from "../keys/KeysPage";
import { MultiBotGrid } from "../overview/MultiBotGrid";
import { GlobalHeader } from "./GlobalHeader";
import { useSessionStore } from "../../session/store";
import { readPreference, savePreference } from "../../session/workspaceUiStore";
import styles from "./shell.module.css";
const WorkspaceCenter = lazy(() =>
  import("../workspace/WorkspaceCenter").then((module) => ({
    default: module.WorkspaceCenter,
  })),
);
const SharedView = lazy(() =>
  import("../workspace/SharedView").then((module) => ({
    default: module.SharedView,
  })),
);
const BotChannel = lazy(() => import("../workspace/ChannelPanel").then(module => ({ default: module.BotChannel })));

export function AppShell({
  user,
  onSignOut,
}: {
  user: User;
  onSignOut: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const bots = useQuery({
    queryKey: ["bots"],
    queryFn: () => api<Bot[]>("/api/bots"),
    refetchInterval: 5000,
  });
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () =>
      api<{
        order: string[];
        folders: Record<string, string>;
        read_cursors: Record<string, number>;
      }>("/api/preferences"),
  });
  const connect = useSessionStore((state) => state.connect);
  const [creating, setCreating] = useState(false);
  const [account, setAccount] = useState(false);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState(
    () => readPreference(`rail:${user.id}`) === "collapsed",
  );
  const match = useMatch("/bots/:id");
  const [params, setParams] = useSearchParams();
  const createFramework = ["ufo", "open_interface"].includes(params.get("newBot") ?? "") ? params.get("newBot")! : undefined;
  function closeCreate() {
    setCreating(false);
    if (createFramework) {
      const next = new URLSearchParams(params);
      next.delete("newBot");
      setParams(next, { replace: true });
    }
  }
  const [lastBot, setLastBot] = useState("");
  const expanded = !!match && params.get("view") === "computer";
  const order = preferences.data?.order ?? [];
  const list = [...(bots.data ?? [])].sort((a, b) => {
    const ai = order.indexOf(a.id),
      bi = order.indexOf(b.id);
    return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
  });
  useEffect(() => {
    if (!bots.data) return;
    const available = new Set(bots.data.map(bot => bot.id));
    for (const id of Object.keys(useSessionStore.getState().sessions)) {
      if (!available.has(id)) {
        useSessionStore.getState().disconnect(id);
        client.removeQueries({ predicate: query => query.queryKey.includes(id) });
      }
    }
    for (const bot of bots.data) connect(bot.id);
  }, [bots.data, connect, client]);
  useEffect(() => {
    let cancelled = false;
    if (bots.data && match?.params.id && !bots.data.some(bot => bot.id === match.params.id)) {
      // The sidebar list is workspace-filtered; confirm lost access to this route.
      void api(`/api/bots/${match.params.id}`).catch(error => {
        if (!cancelled && error instanceof ApiError && error.status === 404) {
          setLastBot("");
          navigate("/workspace", { replace: true });
        }
      });
    }
    return () => { cancelled = true; };
  }, [bots.data, match?.params.id, navigate]);
  useEffect(() => {
    if (match?.params.id) setLastBot(match.params.id);
  }, [match?.params.id]);
  const botId = match?.params.id ?? (lastBot || list[0]?.id);
  const currentBot =
    botId && list.some((bot) => bot.id === botId) ? botId : list[0]?.id;
  const botRoute = currentBot ? `/bots/${currentBot}` : "/overview";
  function toggleRail() {
    if (expanded) {
      navigate(botRoute);
      return;
    }
    setCollapsed((value) => {
      savePreference(`rail:${user.id}`, value ? "expanded" : "collapsed");
      return !value;
    });
  }
  return (
    <div className={styles.shell} data-collapsed={collapsed || expanded}>
      <GlobalHeader
        user={user}
        bots={list}
        search={search}
        onSearch={setSearch}
        onCreate={() => setCreating(true)}
        account={account}
        onAccount={setAccount}
        onSignOut={onSignOut}
      />
      <Sidebar
        folders={preferences.data?.folders}
        readCursors={preferences.data?.read_cursors}
        bots={list.filter((bot) =>
          bot.name.toLowerCase().includes(search.toLowerCase()),
        )}
        total={list.length}
        collapsed={collapsed || expanded}
        onToggle={toggleRail}
        onCreate={() => setCreating(true)}
      />
      <main className={styles.content} id="main-content" tabIndex={-1}>
        {bots.isError ? (
          <div className={styles.loadError} role="alert">
            Could not load your bots.{" "}
            <button onClick={() => void bots.refetch()}>Try again</button>
          </div>
        ) : null}
        {bots.isPending ? (
          <EmptyState title="Loading your bots" />
        ) : (
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route
              path="/overview"
              element={
                <MultiBotGrid bots={list} onCreate={() => setCreating(true)} />
              }
            />
            <Route path="/keys" element={<KeysPage />} />
            <Route path="/channel" element={<Suspense fallback={<p>Loading bot channel…</p>}><BotChannel /></Suspense>} />
            <Route
              path="/workspace"
              element={
                <Suspense fallback={<p>Loading workspace settings…</p>}>
                  <WorkspaceCenter />
                </Suspense>
              }
            />
            <Route
              path="/shares/:id"
              element={
                <Suspense fallback={<p>Loading share…</p>}>
                  <SharedView />
                </Suspense>
              }
            />
            <Route path="/bots/:id" element={<BotWorkspace />} />
            <Route
              path="*"
              element={
                <EmptyState title="Page not found">
                  <Link to="/overview">Return to your bots</Link>
                </EmptyState>
              }
            />
          </Routes>
        )}
      </main>
      <nav className={styles.mobileNav} aria-label="Mobile navigation">
        <Link to="/overview" aria-current={!match ? "page" : undefined}>
          <Icon name="grid" />
          Bots
        </Link>
        <Link
          to={botRoute}
          aria-current={match && !expanded ? "page" : undefined}
        >
          <Icon name="bot" />
          Chat
        </Link>
        <Link
          to={currentBot ? `${botRoute}?view=computer&tab=screen` : "/overview"}
          aria-current={expanded ? "page" : undefined}
        >
          <Icon name="computer" />
          Computer
        </Link>
        <button className="ghost" onClick={() => setAccount(true)}>
          <Icon name="more" />
          More
        </button>
      </nav>
      <CreateBotDialog
        open={creating || !!createFramework}
        initialFramework={createFramework}
        onClose={closeCreate}
        onCreated={async (bot) => {
          setCreating(false);
          await client.invalidateQueries({ queryKey: ["bots"] });
          navigate(`/bots/${bot.id}`);
        }}
      />
    </div>
  );
}

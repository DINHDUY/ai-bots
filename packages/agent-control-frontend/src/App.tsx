import { useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { HashRouter } from "react-router-dom";
import { api, type User } from "./api/client";
import { AuthScreen } from "./features/auth/AuthScreen";
import { AppShell } from "./features/shell/AppShell";
import { EmptyState } from "./components/ui/EmptyState";
import { resetSessions } from "./session/store";
import { resetHumanControl } from "./session/humanControl";

export function App() {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <HashRouter>
        <Gate />
      </HashRouter>
    </QueryClientProvider>
  );
}
function Gate() {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/api/me"),
  });
  if (me.isPending)
    return (
      <EmptyState title="Opening your workspace">
        Loading your account…
      </EmptyState>
    );
  if (me.isError || !me.data)
    return (
      <AuthScreen
        onSignedIn={(user) => {
          resetSessions();
          queryClient.setQueryData(["me"], user);
        }}
      />
    );
  return (
    <AppShell
      key={me.data.id}
      user={me.data}
      onSignOut={async () => {
        await api("/api/logout", { method: "POST" });
        resetHumanControl();
        resetSessions();
        queryClient.clear();
      }}
    />
  );
}

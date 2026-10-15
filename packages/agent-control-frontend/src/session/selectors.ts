import type { BotSession, BotStatus, FileEntry } from "./reduce";
export const statusLabels: Record<BotStatus, string> = {
  idle: "Idle",
  running: "Working",
  stopping: "Stopping",
  awaiting: "Waiting for approval",
  closed: "Closed",
  error: "Error",
  unknown: "Status unknown",
};
export function latestActivity(session?: BotSession): string {
  return session?.activity.at(-1)?.text ?? "Ready for a new task";
}
export function observedFiles(files: FileEntry[]): FileEntry[] {
  return [...new Map(files.map((file) => [file.path, file])).values()].sort(
    (a, b) => a.path.localeCompare(b.path),
  );
}
export function protectedFile(path: string): boolean {
  const name =
    path.replaceAll("\\", "/").split("/").at(-1)?.toLowerCase() ?? "";
  return (
    name === ".env" ||
    name.startsWith(".env.") ||
    name.endsWith(".env") ||
    /\.(pem|key|p12|pfx)$/.test(name) ||
    ["credentials", "credentials.json", "id_rsa", "id_ed25519"].includes(name)
  );
}
export function clockLabel(at?: number): string {
  return at === undefined
    ? ""
    : new Date(at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
}

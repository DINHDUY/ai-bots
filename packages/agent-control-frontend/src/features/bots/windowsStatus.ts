export type WindowsDevice = {
  id: string;
  name: string;
  online: boolean;
  state: {
    sharing: boolean;
    armed: boolean;
    ready: boolean;
    reason: string;
  } | null;
};
export function windowsStatus(pc: WindowsDevice, unavailable = "Windows unavailable") {
  if (!pc.online) return "Offline";
  if (!pc.state?.ready) return pc.state?.reason || unavailable;
  if (!pc.state.sharing) return "Sharing off";
  if (!pc.state.armed) return "Control off";
  return "Ready";
}

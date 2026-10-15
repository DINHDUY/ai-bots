import type { BotStatus } from "../../session/reduce";
import { statusLabels } from "../../session/selectors";
export function StatusBadge({ status, label }: { status: BotStatus; label?: string }) {
  return (
    <span className="badge" data-status={status}>
      <i className="dot" />
      {label ?? statusLabels[status]}
    </span>
  );
}

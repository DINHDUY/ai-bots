import type { CSSProperties } from "react";
import { Icon } from "./Icon";
export function Avatar({
  name,
  id,
  person = false,
}: {
  name: string;
  id: string;
  person?: boolean;
}) {
  const colors = [
    "var(--accent)",
    "var(--violet)",
    "var(--ok)",
    "var(--thinking)",
  ];
  const hash = [...id].reduce((sum, letter) => sum + letter.charCodeAt(0), 0);
  return (
    <span
      className="avatar"
      aria-hidden="true"
      style={
        {
          "--avatar-color": colors[hash % colors.length],
          borderRadius: person ? "50%" : undefined,
        } as CSSProperties
      }
    >
      {person ? name.slice(0, 2).toUpperCase() : <Icon name="bot" />}
    </span>
  );
}

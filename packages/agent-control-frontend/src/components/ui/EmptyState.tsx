import { Icon, type IconName } from "./Icon";
export function EmptyState({
  icon = "computer",
  title,
  children,
}: {
  icon?: IconName;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <Icon name={icon} />
      <h2>{title}</h2>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

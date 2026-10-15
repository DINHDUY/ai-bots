import type { ButtonHTMLAttributes } from "react";
export function Button({
  variant = "default",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "ghost" | "danger";
}) {
  return (
    <button type="button" className={`${variant} ${className}`} {...props} />
  );
}

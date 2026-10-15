import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
export function Dialog({
  open,
  onClose,
  title,
  children,
  className = "",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => {
      dialog.close();
      trigger?.focus();
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <dialog
      ref={ref}
      className={`dialog-shell ${className}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="dialog-heading">
        <h2 id={titleId}>{title}</h2>
        <span className="spacer" />
        <button
          className="icon-button ghost"
          type="button"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </header>
      <div className="dialog-content">{children}</div>
    </dialog>,
    document.body,
  );
}

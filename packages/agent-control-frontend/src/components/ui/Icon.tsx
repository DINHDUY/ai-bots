const icons = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  bot: (
    <>
      <rect x="4" y="7" width="16" height="13" rx="4" />
      <path d="M12 3v4M9 13h.01M15 13h.01M9 17h6M1 12v4M23 12v4" />
    </>
  ),
  spark: (
    <>
      <path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z" />
    </>
  ),
  chart: (
    <>
      <path d="M4 3v18h17M8 16v-4M13 16V7M18 16v-7" />
    </>
  ),
  code: (
    <>
      <path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  chevron: (
    <>
      <path d="m8 10 4 4 4-4" />
    </>
  ),
  right: (
    <>
      <path d="m9 6 6 6-6 6" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14M5 12h14" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  settings: (
    <>
      <path d="m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  plug: (
    <>
      <path d="m7 3 4 4m6-4-4 4M5 9h14v3a7 7 0 0 1-14 0V9Zm7 10v3" />
    </>
  ),
  panel: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
    </>
  ),
  computer: (
    <>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8m-4-4v4" />
    </>
  ),
  expand: (
    <>
      <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />
    </>
  ),
  browser: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M3 8h18M7 5.5h.01M10 5.5h.01" />
    </>
  ),
  terminal: (
    <>
      <path d="m5 7 5 5-5 5m8 0h6" />
    </>
  ),
  folder: (
    <>
      <path d="M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    </>
  ),
  activity: (
    <>
      <path d="M2 12h5l3-8 4 16 3-8h5" />
    </>
  ),
  check: (
    <>
      <path d="m5 12 4 4L19 6" />
    </>
  ),
  checkCircle: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  shield: (
    <>
      <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  arrow: (
    <>
      <path d="M4 12h15m-6-6 6 6-6 6" />
    </>
  ),
  back: (
    <>
      <path d="M20 12H5m6-6-6 6 6 6" />
    </>
  ),
  attach: (
    <>
      <path d="m8 13 7-7a3 3 0 0 1 4 4L9 20a5 5 0 0 1-7-7L13 2" />
    </>
  ),
  file: (
    <>
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-7-7Z" />
      <path d="M13 2v7h7M8 13h8m-8 4h6" />
    </>
  ),
  uploadFile: (
    <>
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-7-7Z" />
      <path d="M13 2v7h7M12 18v-7m-3 3 3-3 3 3" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="2" width="6" height="13" rx="3" />
      <path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8" />
    </>
  ),
  up: (
    <>
      <path d="M12 20V4m-6 6 6-6 6 6" />
    </>
  ),
  record: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V6a4 4 0 0 1 8 0v4m-4 5v2" />
    </>
  ),
  cursor: (
    <>
      <path d="m4 2 15 12-7 1-4 6L4 2Z" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 7a9 9 0 1 0 1 8M20 2v6h-6" />
    </>
  ),
  share: (
    <>
      <path d="M12 15V2m-5 5 5-5 5 5M5 12H3v9h18v-9h-2" />
    </>
  ),
  split: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 14h18" />
    </>
  ),
  columns: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M12 3v18" />
    </>
  ),
  cloud: (
    <>
      <path d="M6 18a5 5 0 1 1 0-10 7 7 0 0 1 13 1 4.5 4.5 0 0 1-1 9H6Z" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  close: <path d="m6 6 12 12M6 18 18 6" />,
  copy: (
    <>
      <rect x="8" y="8" width="12" height="13" rx="2" />
      <path d="M16 8V3H3v13h5" />
    </>
  ),
};
export type IconName = keyof typeof icons;
export function Icon({
  name,
  className = "",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg className={`icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      {icons[name]}
    </svg>
  );
}

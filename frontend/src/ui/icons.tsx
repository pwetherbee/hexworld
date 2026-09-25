const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const HexLogo = () => (
  <svg viewBox="0 0 100 100" width="16" height="16" aria-hidden>
    <polygon points="50,4 90,27 90,73 50,96 10,73 10,27" fill="currentColor" />
  </svg>
);
export const IconChevron = () => (
  <svg {...base}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
export const IconPlus = () => (
  <svg {...base}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const IconClose = () => (
  <svg {...base}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);
export const IconSound = ({ muted }: { muted: boolean }) => (
  <svg {...base}>
    <path d="M11 5 6 9H3v6h3l5 4z" />
    {muted ? <path d="m16 9 5 6m0-6-5 6" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />}
  </svg>
);
export const IconFollow = ({ on }: { on: boolean }) => (
  <svg {...base}>
    <circle cx="12" cy="12" r="3" fill={on ? "currentColor" : "none"} />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    <circle cx="12" cy="12" r="7.5" />
  </svg>
);
export const IconPanel = () => (
  <svg {...base}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M15 4v16" />
  </svg>
);

// Small inline icon set (stroke icons, currentColor).
import type { SVGProps } from "react";

const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 24 24",
  "aria-hidden": true,
};

export const SearchIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const GridIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}>
    <rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" />
  </svg>
);
export const ListIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" />
    <circle cx="4.5" cy="18" r="1" />
  </svg>
);
export const PlusIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>
);
export const HeartIcon = ({ filled, ...p }: SVGProps<SVGSVGElement> & { filled?: boolean }) => (
  <svg {...base} {...p} fill={filled ? "currentColor" : "none"}>
    <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
  </svg>
);
export const PencilIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="m14 6 4 4" /></svg>
);
export const TrashIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>
);
export const UpIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="m6 15 6-6 6 6" /></svg>
);
export const DownIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="m6 9 6 6 6-6" /></svg>
);
export const CameraIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}>
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" />
  </svg>
);
export const PrinterIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}><path d="M7 9V4h10v5M7 17H4v-7h16v7h-3M7 14h10v6H7z" /></svg>
);
export const SunIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" />
  </svg>
);

/** The Collander mark, without the app-icon background. */
export const Logo = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="30 150 452 280" aria-hidden="true" {...p}>
    <rect x="186" y="384" width="140" height="34" rx="12" fill="var(--ink)" />
    <path d="M92 212h328c0 112-70 184-164 184S92 324 92 212z" fill="var(--cobalt)" />
    <rect x="34" y="190" width="92" height="40" rx="20" fill="none" stroke="var(--ink)" strokeWidth="18" />
    <rect x="386" y="190" width="92" height="40" rx="20" fill="none" stroke="var(--ink)" strokeWidth="18" />
    <rect x="74" y="186" width="364" height="48" rx="24" fill="var(--ink)" />
    <g fill="var(--paper)">
      <circle cx="160" cy="270" r="14" /><circle cx="208" cy="270" r="14" /><circle cx="256" cy="270" r="14" />
      <circle cx="304" cy="270" r="14" /><circle cx="352" cy="270" r="14" />
      <circle cx="184" cy="314" r="13" /><circle cx="232" cy="314" r="13" /><circle cx="280" cy="314" r="13" />
      <circle cx="328" cy="314" r="13" />
      <circle cx="220" cy="354" r="11" /><circle cx="256" cy="354" r="11" /><circle cx="292" cy="354" r="11" />
    </g>
  </svg>
);

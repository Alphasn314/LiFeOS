import type { SVGProps } from "react";

export type IconName =
  | "today"
  | "tasks"
  | "pulse"
  | "audit"
  | "settings"
  | "refresh"
  | "plus"
  | "edit"
  | "trash"
  | "check"
  | "warning"
  | "device"
  | "shield"
  | "clock"
  | "close"
  | "chevron";

const paths: Record<IconName, JSX.Element> = {
  today: <path d="M5 3v3m14-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Zm3 8h3v3H8v-3Z" />,
  tasks: <path d="m4 6 1.5 1.5L8 5m2 2h10M4 12l1.5 1.5L8 11m2 2h10M4 18l1.5 1.5L8 17m2 2h10" />,
  pulse: <path d="M3 12h4l2.4-6 4 12 2.2-6H21M5 4h14v16H5z" />,
  audit: <path d="M7 3h10v4H7zM5 5H3v16h18V5h-2M7 12h10M7 16h7" />,
  settings: (
    <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm0-5 1.2 2.1 2.4.5 2-1.2 1.5 1.5-1.2 2 .5 2.4 2.1 1.2v2.1l-2.1 1.2-.5 2.4 1.2 2-1.5 1.5-2-1.2-2.4.5-1.2 2.1H9.9l-1.2-2.1-2.4-.5-2 1.2-1.5-1.5 1.2-2-.5-2.4-2.1-1.2v-2.1l2.1-1.2.5-2.4-1.2-2 1.5-1.5 2 1.2 2.4-.5 1.2-2.1H12Z" />
  ),
  refresh: <path d="M20 7v5h-5M4 17v-5h5m10.2-4A8 8 0 0 0 5.5 6M4.8 16A8 8 0 0 0 18.5 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  edit: <path d="m4 16-1 5 5-1L19 9l-4-4L4 16Zm9-9 4 4" />,
  trash: <path d="M4 7h16M9 3h6l1 4H8l1-4Zm-3 4 1 14h10l1-14M10 11v6m4-6v6" />,
  check: <path d="m4 12 5 5L20 6" />,
  warning: <path d="M12 3 2.5 20h19L12 3Zm0 6v5m0 3h.01" />,
  device: <path d="M4 4h16v12H4zM8 20h8m-4-4v4" />,
  shield: <path d="M12 3 4 6v5c0 5 3.3 8.3 8 10 4.7-1.7 8-5 8-10V6l-8-3Zm-4 9 2.5 2.5L16 9" />,
  clock: <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3.5 2" />,
  close: <path d="m5 5 14 14M19 5 5 19" />,
  chevron: <path d="m9 6 6 6-6 6" />,
};

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 20, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

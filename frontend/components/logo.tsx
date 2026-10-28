import type { SVGProps } from "react";

// Chip die with pins; the core is a Manhattan-routed "S" trace, like a wire in a layout.
export function Logo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <rect x="5" y="5" width="14" height="14" rx="2.5" />
      <path d="M9 2v3M12 2v3M15 2v3M9 19v3M12 19v3M15 19v3M2 9h3M2 12h3M2 15h3M19 9h3M19 12h3M19 15h3" />
      <path d="M15 9h-6v3h6v3H9" />
    </svg>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Navigation() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation">
      <Link href="/" aria-current={pathname === "/" ? "page" : undefined}>New design</Link>
      <Link href="/runs" aria-current={pathname.startsWith("/runs") ? "page" : undefined}>Run history</Link>
    </nav>
  );
}

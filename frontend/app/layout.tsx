import type { Metadata } from "next";
import Link from "next/link";
import { Navigation } from "@/components/navigation";
import "./globals.css";

export const metadata: Metadata = {
  title: "Silicon Agent — From an idea to silicon",
  description: "Describe a small digital chip. Follow every tool run, test, and layout.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <div className="header-inner">
            <Link href="/" className="wordmark">Silicon Agent</Link>
            <Navigation />
          </div>
        </header>
        <main className="main-content">{children}</main>
        <footer className="site-footer"><div>Real tools. Inspectable results.</div></footer>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { AppSidebar } from "@/components/app-sidebar";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { appearanceScript } from "@/lib/appearance";
import "./globals.css";

export const metadata: Metadata = {
  title: "Silicon Agent — From an idea to silicon",
  description: "Describe a small digital chip. Follow every tool run, test, and layout.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The head script swaps the server-rendered dark default for the stored mode before paint.
    <html lang="en" className="dark" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: appearanceScript }} /></head>
      <body>
        <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:outline-2 focus:outline-offset-2">Skip to main content</a>
        <TooltipProvider>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset className="min-w-0">
              <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur">
                <SidebarTrigger className="-ml-1" />
                <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
                <span className="text-sm text-muted-foreground">Real tools. Inspectable results.</span>
              </header>
              <div id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1920px] flex-1 scroll-mt-16 px-4 py-6 focus-visible:outline-2 focus-visible:outline-ring sm:px-6">{children}</div>
            </SidebarInset>
          </SidebarProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}

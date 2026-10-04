import type { Metadata, Viewport } from "next";
import { Geist_Mono, Inter } from "next/font/google";
import { cookies } from "next/headers";

import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { ThemeScript } from "@/components/theme-script";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Tollgate", template: "%s · Tollgate" },
  description: "OpenAI-compatible LLM gateway dashboard",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f7f8" },
    { media: "(prefers-color-scheme: dark)", color: "#08090a" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Persisted by the shadcn sidebar so the collapsed state survives reloads without a layout shift.
  const sidebarOpen = (await cookies()).get("sidebar_state")?.value !== "false";

  return (
    // suppressHydrationWarning: ThemeScript sets class/style on <html> before React hydrates.
    <html lang="en" className={`${inter.variable} ${geistMono.variable} antialiased`} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        <TooltipProvider>
          <SidebarProvider defaultOpen={sidebarOpen}>
            <AppSidebar />
            <SidebarInset className="md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:shadow-none">
              <SiteHeader />
              <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</div>
            </SidebarInset>
          </SidebarProvider>
          <Toaster position="bottom-right" />
        </TooltipProvider>
      </body>
    </html>
  );
}

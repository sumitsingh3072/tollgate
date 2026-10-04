import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";
import { Geist_Mono, Inter } from "next/font/google";

import { ThemeScript } from "@/components/theme-script";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CLERK_ENABLED } from "@/lib/auth-config";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Tollgate — OpenAI-compatible LLM gateway", template: "%s · Tollgate" },
  description:
    "API keys, rate limits, token quotas, caching, fallback and analytics in front of your models. Change one line: base_url.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f7f8" },
    { media: "(prefers-color-scheme: dark)", color: "#08090a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  const content = (
    <TooltipProvider>
      {children}
      <Toaster position="bottom-right" />
    </TooltipProvider>
  );
  return (
    // suppressHydrationWarning: ThemeScript sets class/style on <html> before React hydrates.
    <html lang="en" className={`${inter.variable} ${geistMono.variable} antialiased`} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        {CLERK_ENABLED ? (
          // Clerk reads our theme tokens through --clerk-* variables in globals.css; sign-in/up URLs
          // come from next.config.ts env so server redirects agree with the client.
          <ClerkProvider afterSignOutUrl="/">{content}</ClerkProvider>
        ) : (
          content
        )}
      </body>
    </html>
  );
}

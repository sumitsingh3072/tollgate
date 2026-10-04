import { auth } from "@clerk/nextjs/server";
import { cookies } from "next/headers";

import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

// Signed-in app shell. Signed-out visitors are sent to /sign-in; every admin call re-checks the user
// (lib/server/gateway.ts), so client-side navigations that skip this layout stay protected too.
export default async function AppLayout({ children }: LayoutProps<"/">) {
  await auth.protect();
  // Persisted by the shadcn sidebar so the collapsed state survives reloads without a layout shift.
  const sidebarOpen = (await cookies()).get("sidebar_state")?.value !== "false";

  return (
    <SidebarProvider defaultOpen={sidebarOpen}>
      <AppSidebar />
      <SidebarInset className="md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:shadow-none">
        <SiteHeader />
        <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}

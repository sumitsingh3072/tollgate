import { SignIn } from "@clerk/nextjs";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AuthShell } from "@/components/auth-shell";
import { CLERK_ENABLED } from "@/lib/auth-config";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  if (!CLERK_ENABLED) redirect("/dashboard"); // local mode: no accounts
  return (
    <AuthShell>
      <SignIn />
    </AuthShell>
  );
}

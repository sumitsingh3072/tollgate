"use client";

import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";

// Catches failed gateway calls in any page (e.g. gateway down) and offers a retry.
export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <ErrorState
      title="Could not load this page"
      message={
        process.env.NODE_ENV === "production"
          ? "The gateway did not respond as expected. Check that it is running, then retry."
          : error.message
      }
      action={
        <Button variant="outline" size="sm" onClick={reset}>
          Try again
        </Button>
      }
    />
  );
}

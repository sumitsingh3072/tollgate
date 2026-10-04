"use client";

import { PlusIcon, TriangleAlertIcon } from "lucide-react";
import { type FormEvent, useState, useTransition } from "react";
import { toast } from "sonner";

import { createKey } from "@/app/actions";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { CreatedApiKey } from "@/lib/types";

const DEFAULTS = { rpm: 60, daily_token_quota: 100_000 };

export function CreateKeyDialog() {
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      // Forget the secret as soon as the dialog closes.
      setCreated(null);
      setError(null);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const input = {
      name: String(form.get("name") ?? "").trim(),
      rpm: Number(form.get("rpm")),
      daily_token_quota: Number(form.get("daily_token_quota")),
    };
    setError(null);
    startTransition(async () => {
      const result = await createKey(input);
      if (result.ok) {
        setCreated(result.data);
        toast.success(`Created "${result.data.name}"`);
      } else {
        setError(result.error);
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger render={<Button size="sm" />}>
        <PlusIcon />
        New key
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Save your key</DialogTitle>
              <DialogDescription>Use it as the API key in any OpenAI-compatible client.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="flex items-center gap-2 rounded-md border bg-muted/50 p-2">
                <code className="flex-1 truncate font-mono text-xs select-all">{created.key}</code>
                <CopyButton value={created.key} />
              </div>
              <p className="flex items-start gap-2 text-xs text-warning">
                <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                This is the only time the full key is shown. Only a hash is stored.
              </p>
            </div>
            <DialogFooter>
              <DialogClose render={<Button />}>Done</DialogClose>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={onSubmit} className="contents">
            <DialogHeader>
              <DialogTitle>New API key</DialogTitle>
              <DialogDescription>Limits apply per key and can&apos;t be changed later.</DialogDescription>
            </DialogHeader>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="key-name">Name</FieldLabel>
                <Input id="key-name" name="name" placeholder="e.g. backend-prod" required maxLength={100} autoFocus />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field>
                  <FieldLabel htmlFor="key-rpm">Requests / minute</FieldLabel>
                  <Input id="key-rpm" name="rpm" type="number" min={1} max={100000} defaultValue={DEFAULTS.rpm} required />
                </Field>
                <Field>
                  <FieldLabel htmlFor="key-quota">Daily tokens</FieldLabel>
                  <Input
                    id="key-quota"
                    name="daily_token_quota"
                    type="number"
                    min={1}
                    max={1000000000}
                    defaultValue={DEFAULTS.daily_token_quota}
                    required
                  />
                </Field>
              </div>
              <FieldDescription>The token quota resets at midnight UTC.</FieldDescription>
              {error && <FieldError>{error}</FieldError>}
            </FieldGroup>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" type="button" />}>Cancel</DialogClose>
              <Button type="submit" disabled={pending}>
                {pending ? "Creating…" : "Create key"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

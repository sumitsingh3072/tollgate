import { useSyncExternalStore } from "react";

const noop = () => () => {};

/** false during SSR and hydration, true afterwards. For output that depends on the viewer's locale/time zone. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}

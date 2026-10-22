import { useEffect, useState } from "react";
import * as bridge from "./bridge";
export function OperationsBadge() {
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let alive = true,
      epoch = 0;
    async function poll() {
      if (document.hidden) {
        epoch++;
        setPending(false);
        return;
      }
      const expected = epoch;
      try {
        const updates = await bridge.api<unknown[]>("/operations/inbox");
        if (alive && expected === epoch) setPending(updates.length > 0);
      } catch {
        if (alive && expected === epoch) setPending(false);
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 5000);
    document.addEventListener("visibilitychange", poll);
    return () => {
      alive = false;
      epoch++;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", poll);
    };
  }, []);
  return pending ? <small role="status"> · Update available</small> : null;
}

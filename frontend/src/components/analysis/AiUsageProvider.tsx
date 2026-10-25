"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { getAiUsage } from "@/lib/api/client";
import type { AiUsage } from "@/lib/api/types";

interface AiUsageContextValue {
  /** Today's allowance from the server, or null when unknown (logged out, loading, or failed to load). */
  usage: AiUsage | null;
  /** Re-read the allowance (call after each analysis attempt). */
  refresh: () => void;
}

const AiUsageContext = createContext<AiUsageContextValue | null>(null);

export function useAiUsage(): AiUsageContextValue {
  const value = useContext(AiUsageContext);
  if (!value) throw new Error("useAiUsage must be used inside <AiUsageProvider>");
  return value;
}

/**
 * Shares the signed-in user's daily AI allowance with every analysis panel (one request,
 * not one per paper card). Display only: the limit itself is enforced by the server.
 */
export function AiUsageProvider({ children }: { children: ReactNode }) {
  const { status, account } = useAuth();
  const userId = status === "authenticated" ? (account?.user.id ?? null) : null;
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [token, setToken] = useState(0);

  // Different user (or logged out): forget the previous allowance immediately.
  const [loadedFor, setLoadedFor] = useState<string | null>(userId);
  if (loadedFor !== userId) {
    setLoadedFor(userId);
    setUsage(null);
  }

  useEffect(() => {
    if (!userId) return;
    const controller = new AbortController();
    getAiUsage(controller.signal)
      .then(setUsage)
      .catch(() => {
        if (!controller.signal.aborted) setUsage(null); // unknown; the server still enforces the limit
      });
    return () => controller.abort();
  }, [userId, token]);

  const refresh = useCallback(() => setToken((n) => n + 1), []);
  const value = useMemo(() => ({ usage, refresh }), [usage, refresh]);
  return <AiUsageContext.Provider value={value}>{children}</AiUsageContext.Provider>;
}

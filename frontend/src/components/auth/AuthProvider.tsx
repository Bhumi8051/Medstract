"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import * as api from "@/lib/api/client";
import type { Account, Preferences } from "@/lib/api/types";

import { AuthDialog, type AuthMode } from "./AuthDialog";

/**
 * - loading: checking the session cookie
 * - anonymous: not logged in
 * - authenticated: logged in
 * - unavailable: the account service can't be reached (search still works)
 */
export type AuthStatus = "loading" | "anonymous" | "authenticated" | "unavailable";

interface AuthContextValue {
  status: AuthStatus;
  account: Account | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  savePreferences: (preferences: Preferences) => Promise<void>;
  /** Open the log-in / sign-up dialog, optionally explaining why. */
  openAuthDialog: (mode?: AuthMode, reason?: string) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** Holds the logged-in account for the whole app. The session itself lives in an HttpOnly cookie. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [account, setAccount] = useState<Account | null>(null);
  const [dialog, setDialog] = useState<{ mode: AuthMode; reason?: string } | null>(null);

  // Ask the backend who we are (the browser sends the session cookie automatically).
  useEffect(() => {
    const controller = new AbortController();
    api
      .getCurrentAccount(controller.signal)
      .then((current) => {
        setAccount(current);
        setStatus(current ? "authenticated" : "anonymous");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("unavailable");
      });
    return () => controller.abort();
  }, []);

  const signedIn = useCallback((next: Account) => {
    setAccount(next);
    setStatus("authenticated");
    setDialog(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      account,
      login: async (email, password) => signedIn(await api.login(email, password)),
      register: async (email, password) => signedIn(await api.register(email, password)),
      logout: async () => {
        await api.logout();
        setAccount(null);
        setStatus("anonymous");
      },
      savePreferences: async (preferences) => {
        const saved = await api.updatePreferences(preferences);
        setAccount((current) => (current ? { ...current, preferences: saved } : current));
      },
      openAuthDialog: (mode = "login", reason) => setDialog({ mode, reason }),
    }),
    [status, account, signedIn],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
      {dialog && (
        <AuthDialog
          initialMode={dialog.mode}
          reason={dialog.reason}
          onClose={() => setDialog(null)}
          onLogin={value.login}
          onRegister={value.register}
        />
      )}
    </AuthContext.Provider>
  );
}

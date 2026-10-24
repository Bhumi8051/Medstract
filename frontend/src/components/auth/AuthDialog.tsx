"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api/client";

export type AuthMode = "login" | "register";

const PASSWORD_MIN_LENGTH = 10; // matches the backend (app/models.py)
const PASSWORD_MAX_LENGTH = 128;

interface AuthDialogProps {
  initialMode: AuthMode;
  reason?: string;
  onClose: () => void;
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string) => Promise<void>;
}

/** Modal log-in / sign-up form built on the native <dialog> element (focus trap and Escape for free). */
export function AuthDialog({ initialMode, reason, onClose, onLogin, onRegister }: AuthDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const baseId = useId();
  const isRegister = mode === "register";

  // Open as a modal once mounted. No cleanup on purpose: calling close() there fires
  // the dialog's "close" event, which React's development double-mount (Strict Mode)
  // turned into "user dismissed it", so the dialog vanished instantly. Removing the
  // element from the page ends the modal anyway.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    // showModal() focuses the first button (✕); start in the email field instead.
    emailRef.current?.focus();
  }, []);

  function switchMode(next: AuthMode) {
    setMode(next);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedEmail = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    if (isRegister && (password.length < PASSWORD_MIN_LENGTH || password.length > PASSWORD_MAX_LENGTH)) {
      setError(`Use a password of ${PASSWORD_MIN_LENGTH} to ${PASSWORD_MAX_LENGTH} characters.`);
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await (isRegister ? onRegister : onLogin)(trimmedEmail, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  const inputClass =
    "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/30 focus:outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100";

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby={`${baseId}-title`}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-xl backdrop:bg-slate-900/50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id={`${baseId}-title`} className="text-lg font-semibold">
              {isRegister ? "Create your account" : "Log in"}
            </h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {reason ?? "Save searches and keep your preferred summary level."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label="Close"
            className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:hover:bg-slate-800"
          >
            ✕
          </button>
        </div>

        <div>
          <label htmlFor={`${baseId}-email`} className="text-sm font-medium">
            Email
          </label>
          <input
            id={`${baseId}-email`}
            type="email"
            autoComplete="email"
            required
            ref={emailRef}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError(null);
            }}
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor={`${baseId}-password`} className="text-sm font-medium">
            Password
          </label>
          <input
            id={`${baseId}-password`}
            type={showPassword ? "text" : "password"}
            autoComplete={isRegister ? "new-password" : "current-password"}
            required
            minLength={isRegister ? PASSWORD_MIN_LENGTH : undefined}
            maxLength={PASSWORD_MAX_LENGTH}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setError(null);
            }}
            aria-describedby={isRegister ? `${baseId}-password-hint` : undefined}
            className={inputClass}
          />
          <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
            {isRegister ? (
              <span id={`${baseId}-password-hint`}>At least {PASSWORD_MIN_LENGTH} characters. A passphrase works well.</span>
            ) : (
              <span />
            )}
            <label className="inline-flex shrink-0 items-center gap-1">
              <input
                type="checkbox"
                checked={showPassword}
                onChange={(e) => setShowPassword(e.target.checked)}
                className="size-3.5 accent-teal-700"
              />
              Show
            </label>
          </div>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-teal-700 px-4 py-2.5 font-semibold text-white transition hover:bg-teal-800 focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-70"
        >
          {submitting ? "Please wait…" : isRegister ? "Create account" : "Log in"}
        </button>

        <p className="text-center text-sm text-slate-600 dark:text-slate-400">
          {isRegister ? "Already have an account?" : "New here?"}{" "}
          <button
            type="button"
            onClick={() => switchMode(isRegister ? "login" : "register")}
            className="font-medium text-teal-800 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:outline-none dark:text-teal-300"
          >
            {isRegister ? "Log in" : "Create an account"}
          </button>
        </p>
      </form>
    </dialog>
  );
}

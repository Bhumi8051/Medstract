"use client";

import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import type { SummaryLevel } from "@/lib/api/types";
import type { Option } from "@/lib/filters";
import {
  defaultSettings,
  describeSchedule,
  formatTime,
  FREQUENCY_OPTIONS,
  listTimeZones,
  PAPER_COUNT_OPTIONS,
  parseTypedTime,
  READING_LEVEL_DESCRIPTIONS,
  READING_LEVEL_OPTIONS,
  TOPIC_MAX_LENGTH,
  validateSettings,
  WEEKDAYS,
  type SettingsErrors,
  type Subscription,
  type SubscriptionSettings,
} from "@/lib/subscriptions";

import type { SubscriptionsStatus } from "./SubscriptionsProvider";

interface SubscriptionDialogProps {
  /** The subscription being managed, or null to create a new one. */
  editing: Subscription | null;
  initialTopic: string;
  initialReadingLevel: SummaryLevel;
  findByTopic: (topic: string) => Subscription | undefined;
  onSwitchToExisting: (subscription: Subscription) => void;
  /** State of the list loaded from the server (duplicates can only be spotted early when it's "ready"). */
  listStatus: SubscriptionsStatus;
  /** Saves to the server; rejects with a user-readable Error on failure. */
  onSave: (settings: SubscriptionSettings, editingId: string | null) => Promise<void>;
  onUnsubscribe: (id: string) => Promise<void>;
  onClose: () => void;
}

const FIELD_ORDER: (keyof SettingsErrors)[] = ["topic", "weekday", "monthDay", "deliveryTime", "timeZone"];

// One look for every text input and select: same height, border, radius and focus ring.
const controlClass =
  "block h-11 w-full rounded-lg border border-navy-300 bg-white px-3 text-sm text-navy-900 shadow-sm transition focus:border-brand-600 focus:ring-2 focus:ring-brand-600/30 focus:outline-none aria-invalid:border-red-500 dark:border-navy-700 dark:bg-navy-950 dark:text-navy-100 dark:[color-scheme:dark]";
const labelClass = "mb-1.5 block text-sm font-medium text-navy-800 dark:text-navy-200";
const hintClass = "mt-1.5 text-xs text-navy-500 dark:text-navy-400";
const errorClass = "mt-1.5 text-sm text-red-700 dark:text-red-400";

/** Create or manage a research subscription. Saved to the server; nothing is delivered yet. */
export function SubscriptionDialog({
  editing,
  initialTopic,
  initialReadingLevel,
  listStatus,
  findByTopic,
  onSwitchToExisting,
  onSave,
  onUnsubscribe,
  onClose,
}: SubscriptionDialogProps) {
  const { status: authStatus, account, openAuthDialog } = useAuth();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const topicRef = useRef<HTMLInputElement>(null);
  const [settings, setSettings] = useState<SubscriptionSettings>(
    () => editing ?? defaultSettings(initialTopic, initialReadingLevel),
  );
  const [errors, setErrors] = useState<SettingsErrors>({});
  const [confirmingUnsubscribe, setConfirmingUnsubscribe] = useState(false);
  const [pending, setPending] = useState<"saving" | "removing" | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const timeZones = useMemo(() => listTimeZones(), []);
  // What the user typed; settings.deliveryTime holds it as "HH:MM", or "" while it isn't valid.
  const [timeText, setTimeText] = useState(() => formatTime(settings.deliveryTime));
  const baseId = useId();
  const id = (name: string) => `${baseId}-${name}`;
  const isEditing = editing !== null;
  const signedIn = authStatus === "authenticated" && account !== null;

  // Another subscription already uses this topic: offer to manage it instead of duplicating.
  const duplicate = useMemo(() => {
    const match = findByTopic(settings.topic);
    return match && match.id !== editing?.id ? match : null;
  }, [findByTopic, settings.topic, editing]);

  // Open as a modal once mounted. No cleanup that calls close(): under React Strict Mode
  // (development) that fires the "close" event and the dialog would vanish instantly.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    topicRef.current?.focus();
  }, []);

  function update<K extends keyof SubscriptionSettings>(field: K, value: SubscriptionSettings[K]) {
    setSettings((current) => ({ ...current, [field]: value }));
    setServerError(null);
    if (field in errors) setErrors((current) => ({ ...current, [field]: undefined }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return; // no double submissions
    if (!signedIn) {
      openAuthDialog("login", "Log in or create a free account to subscribe to research updates.");
      return;
    }
    const nextErrors = validateSettings(settings, timeZones);
    if (duplicate) nextErrors.topic = "You already follow this topic.";
    setErrors(nextErrors);
    const firstInvalid = FIELD_ORDER.find((field) => nextErrors[field]);
    if (firstInvalid) {
      document.getElementById(id(firstInvalid))?.focus();
      return;
    }
    setPending("saving");
    setServerError(null);
    try {
      await onSave(settings, editing?.id ?? null); // closes the dialog on success
    } catch (error) {
      setServerError(error instanceof Error ? error.message : "The subscription could not be saved.");
      setPending(null);
    }
  }

  async function handleUnsubscribe() {
    if (!editing || pending) return;
    setPending("removing");
    setServerError(null);
    try {
      await onUnsubscribe(editing.id);
    } catch (error) {
      setServerError(error instanceof Error ? error.message : "The subscription could not be removed.");
      setPending(null);
      setConfirmingUnsubscribe(false);
    }
  }

  const showDayField = settings.frequency !== "daily";

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby={id("title")}
      aria-describedby={id("status")}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(38rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-navy-200 bg-white p-0 text-navy-900 shadow-2xl backdrop:bg-navy-900/60 backdrop:backdrop-blur-sm dark:border-navy-700 dark:bg-navy-900 dark:text-navy-100"
    >
      <form onSubmit={handleSubmit} noValidate>
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-navy-200 bg-white/95 px-6 py-5 backdrop-blur dark:border-navy-800 dark:bg-navy-900/95">
          <span
            aria-hidden="true"
            className="grid size-11 shrink-0 place-items-center rounded-full bg-brand-700 text-white shadow-sm"
          >
            <BellGlyph ringing className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id={id("title")} className="text-lg leading-tight font-semibold">
              {isEditing ? "Manage research subscription" : "Subscribe to research updates"}
            </h2>
            <p className="mt-1 text-sm text-navy-600 dark:text-navy-400">
              The newest PubMed papers on a topic, summarized at your reading level.
            </p>
          </div>
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label="Close"
            className="-mt-1 -mr-2 grid size-9 place-items-center rounded-lg text-navy-500 transition hover:bg-navy-100 hover:text-navy-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:hover:bg-navy-800 dark:hover:text-navy-100"
          >
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="divide-y divide-navy-200 dark:divide-navy-800">
          {/* Status + topic */}
          <div className="space-y-5 px-6 py-5">
            <div
              id={id("status")}
              className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100"
            >
              <svg viewBox="0 0 24 24" className="mt-0.5 size-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 8v5M12 16.5v.01" strokeLinecap="round" />
              </svg>
              <div>
                <p className="font-semibold">Automatic emails aren&rsquo;t active yet</p>
                <p className="mt-0.5 text-amber-900 dark:text-amber-200/90">
                  Your subscription and delivery settings are saved to your account, but nothing is sent on this
                  schedule yet: automatic delivery needs a scheduler, which hasn&rsquo;t been built. You can send
                  yourself a one-off test email from your account page.
                </p>
              </div>
            </div>

            <div>
              <label htmlFor={id("topic")} className={labelClass}>
                Topic
              </label>
              <input
                ref={topicRef}
                id={id("topic")}
                value={settings.topic}
                maxLength={TOPIC_MAX_LENGTH}
                placeholder="e.g. metformin breast cancer"
                autoComplete="off"
                onChange={(e) => update("topic", e.target.value)}
                aria-invalid={Boolean(errors.topic)}
                aria-describedby={`${id("topic-hint")}${errors.topic ? ` ${id("topic-error")}` : ""}`}
                className={controlClass}
              />
              {errors.topic ? (
                <p id={id("topic-error")} className={errorClass}>
                  {errors.topic}
                </p>
              ) : (
                <p id={id("topic-hint")} className={hintClass}>
                  Keywords or a question, searched in PubMed like the main search box.
                </p>
              )}
              {signedIn && listStatus === "error" && (
                <p className={hintClass}>
                  Your existing subscriptions couldn&rsquo;t be loaded, so duplicates will be checked when you save.
                </p>
              )}
              {duplicate && (
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-950 dark:bg-brand-950/40 dark:text-brand-100">
                  <span>
                    You already follow <strong>&ldquo;{duplicate.topic}&rdquo;</strong>.
                  </span>
                  <button
                    type="button"
                    onClick={() => onSwitchToExisting(duplicate)}
                    className="font-semibold text-brand-800 underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-brand-300"
                  >
                    Manage that subscription
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Schedule */}
          <Section title="Schedule">
            <ChoiceGroup
              legend="How often"
              name={id("frequency")}
              options={FREQUENCY_OPTIONS}
              value={settings.frequency}
              onChange={(value) => update("frequency", value)}
              columns="grid-cols-3"
            />

            <div className={`grid gap-4 ${showDayField ? "sm:grid-cols-2" : ""}`}>
              {settings.frequency === "weekly" && (
                <div>
                  <label htmlFor={id("weekday")} className={labelClass}>
                    Delivery day
                  </label>
                  <Select
                    id={id("weekday")}
                    value={String(settings.weekday)}
                    onChange={(value) => update("weekday", Number(value))}
                    invalid={Boolean(errors.weekday)}
                  >
                    {WEEKDAYS.map((day, index) => (
                      <option key={day} value={index}>
                        {day}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
              {settings.frequency === "monthly" && (
                <div>
                  <label htmlFor={id("monthDay")} className={labelClass}>
                    Day of month
                  </label>
                  <Select
                    id={id("monthDay")}
                    value={String(settings.monthDay)}
                    onChange={(value) => update("monthDay", Number(value))}
                    invalid={Boolean(errors.monthDay)}
                    describedBy={id("monthDay-hint")}
                  >
                    {Array.from({ length: 28 }, (_, i) => i + 1).map((day) => (
                      <option key={day} value={day}>
                        {day}
                      </option>
                    ))}
                  </Select>
                  <p id={id("monthDay-hint")} className={hintClass}>
                    1–28, so it exists every month.
                  </p>
                </div>
              )}
              <div>
                <label htmlFor={id("deliveryTime")} className={labelClass}>
                  Delivery time
                </label>
                <input
                  id={id("deliveryTime")}
                  type="text"
                  inputMode="text"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="e.g., 7:30 PM"
                  value={timeText}
                  onChange={(event) => {
                    setTimeText(event.target.value);
                    update("deliveryTime", parseTypedTime(event.target.value) ?? "");
                  }}
                  // Tidy a valid entry ("7:30pm" -> "7:30 PM") once the user moves on.
                  onBlur={() => {
                    const parsed = parseTypedTime(timeText);
                    if (parsed) setTimeText(formatTime(parsed));
                  }}
                  className={controlClass}
                  aria-invalid={Boolean(errors.deliveryTime)}
                  aria-describedby={errors.deliveryTime ? id("deliveryTime-error") : undefined}
                />
                {errors.deliveryTime && (
                  <p id={id("deliveryTime-error")} className={errorClass}>
                    {errors.deliveryTime}
                  </p>
                )}
              </div>
            </div>

            <div>
              <label htmlFor={id("timeZone")} className={labelClass}>
                Time zone
              </label>
              <Select
                id={id("timeZone")}
                value={settings.timeZone}
                onChange={(value) => update("timeZone", value)}
                invalid={Boolean(errors.timeZone)}
              >
                {timeZones.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone.replace(/_/g, " ")}
                  </option>
                ))}
              </Select>
              {errors.timeZone && <p className={errorClass}>{errors.timeZone}</p>}
            </div>

            <p className="flex items-center gap-2 rounded-lg bg-navy-50 px-3 py-2.5 text-sm text-navy-700 dark:bg-navy-800/60 dark:text-navy-300">
              <svg viewBox="0 0 24 24" className="size-4 shrink-0 text-brand-700 dark:text-brand-400" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <rect x="3" y="5" width="18" height="16" rx="2" />
                <path d="M3 10h18M8 3v4M16 3v4" strokeLinecap="round" />
              </svg>
              <span>
                <span className="font-medium text-navy-900 dark:text-navy-100">Schedule:</span>{" "}
                {describeSchedule(settings)}
              </span>
            </p>
          </Section>

          {/* Each report */}
          <Section title="Each report">
            <ChoiceGroup
              legend="Number of papers"
              name={id("count")}
              options={PAPER_COUNT_OPTIONS}
              value={String(settings.paperCount) as "5" | "10" | "15" | "20"}
              onChange={(value) => update("paperCount", Number(value) as SubscriptionSettings["paperCount"])}
              columns="grid-cols-4"
              hint="The newest, most relevant papers since the last report."
            />
            <ChoiceGroup
              legend="Reading level"
              name={id("level")}
              options={READING_LEVEL_OPTIONS}
              value={settings.readingLevel}
              onChange={(value) => update("readingLevel", value)}
              columns="grid-cols-1"
              descriptions={READING_LEVEL_DESCRIPTIONS}
            />
          </Section>

          {/* Email delivery */}
          <Section title="Email delivery">
            <div className="divide-y divide-navy-200 overflow-hidden rounded-xl border border-navy-200 dark:divide-navy-800 dark:border-navy-700">
              <SettingRow
                htmlFor={id("autoEmail")}
                title="Automatic email delivery"
                description={
                  signedIn
                    ? `Reports would go to ${account.user.email}. Not active yet.`
                    : "Reports would go to your account's email address. Not active yet."
                }
                descriptionId={id("autoEmail-hint")}
              >
                <input
                  id={id("autoEmail")}
                  type="checkbox"
                  role="switch"
                  checked={settings.autoEmail}
                  onChange={(e) => update("autoEmail", e.target.checked)}
                  aria-describedby={id("autoEmail-hint")}
                  className="peer sr-only"
                />
                <label
                  htmlFor={id("autoEmail")}
                  aria-hidden="true"
                  className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full bg-navy-300 transition peer-checked:bg-brand-700 peer-focus-visible:ring-2 peer-focus-visible:ring-brand-600 peer-focus-visible:ring-offset-2 after:absolute after:left-0.5 after:size-5 after:rounded-full after:bg-white after:shadow after:transition peer-checked:after:translate-x-5 dark:bg-navy-600 dark:peer-focus-visible:ring-offset-navy-900"
                />
              </SettingRow>
              <SettingRow
                htmlFor={id("emailEmpty")}
                title="Email me even when there are no new papers."
                description="Otherwise a report is skipped when nothing new was published."
                disabled={!settings.autoEmail}
              >
                <input
                  id={id("emailEmpty")}
                  type="checkbox"
                  checked={settings.emailWhenNoNewPapers}
                  disabled={!settings.autoEmail}
                  onChange={(e) => update("emailWhenNoNewPapers", e.target.checked)}
                  className="size-5 shrink-0 cursor-pointer rounded border-navy-300 accent-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </SettingRow>
            </div>
          </Section>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-navy-200 bg-white/95 px-6 py-4 backdrop-blur dark:border-navy-800 dark:bg-navy-900/95">
          {isEditing &&
            (confirmingUnsubscribe ? (
              <span className="flex items-center gap-2 text-sm">
                Unsubscribe?
                <button
                  type="button"
                  onClick={handleUnsubscribe}
                  disabled={pending !== null}
                  className="h-9 rounded-lg bg-red-700 px-3 font-medium text-white hover:bg-red-800 focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                >
                  {pending === "removing" ? "Removing…" : "Yes, unsubscribe"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingUnsubscribe(false)}
                  className="h-9 rounded-lg px-2 font-medium text-navy-600 hover:bg-navy-100 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:text-navy-300 dark:hover:bg-navy-800"
                >
                  Keep
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingUnsubscribe(true)}
                className="text-sm font-medium text-red-700 underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none dark:text-red-400"
              >
                Unsubscribe
              </button>
            ))}
          {serverError && (
            <p role="alert" className="order-first w-full rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/50 dark:text-red-200">
              {serverError}
            </p>
          )}
          <div className="ml-auto flex gap-3">
            <button
              type="button"
              onClick={() => dialogRef.current?.close()}
              className="h-11 rounded-lg border border-navy-300 px-5 text-sm font-medium text-navy-800 transition hover:border-navy-400 hover:bg-navy-50 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:outline-none dark:border-navy-700 dark:text-navy-100 dark:hover:bg-navy-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={pending !== null}
              className="h-11 rounded-lg bg-brand-700 px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-wait disabled:opacity-70 dark:focus-visible:ring-offset-navy-900"
            >
              {pending === "saving"
                ? "Saving…"
                : !signedIn
                  ? "Log in to subscribe"
                  : isEditing
                    ? "Save changes"
                    : "Subscribe"}
            </button>
          </div>
        </div>
      </form>
    </dialog>
  );
}

/** A titled block of the form. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-5 px-6 py-5">
      <legend className="float-left mb-4 w-full text-base font-semibold text-navy-900 dark:text-navy-50">
        {title}
      </legend>
      <div className="clear-both space-y-5">{children}</div>
    </fieldset>
  );
}

interface ChoiceGroupProps<T extends string> {
  legend: string;
  name: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Tailwind grid-cols classes so every choice in the row has the same width. */
  columns: string;
  hint?: string;
  descriptions?: Partial<Record<T, string>>;
}

/** Equal-width choice tiles built on native radios (arrow keys move between them). */
function ChoiceGroup<T extends string>({ legend, name, options, value, onChange, columns, hint, descriptions }: ChoiceGroupProps<T>) {
  const hintId = `${name}-hint`;
  return (
    <fieldset aria-describedby={hint ? hintId : undefined}>
      <legend className={labelClass}>{legend}</legend>
      <div className={`grid gap-2 ${columns}`}>
        {options.map((option) => {
          const description = descriptions?.[option.value];
          return (
            <label
              key={option.value}
              className={`relative flex cursor-pointer rounded-lg border text-sm transition has-focus-visible:ring-2 has-focus-visible:ring-brand-600 has-focus-visible:ring-offset-2 dark:has-focus-visible:ring-offset-navy-900 ${
                description ? "items-center justify-between gap-4 px-4 py-3" : "h-11 items-center justify-center px-3"
              } ${
                value === option.value
                  ? "border-brand-600 bg-brand-50 text-brand-900 ring-1 ring-brand-600 dark:border-brand-500 dark:bg-brand-950/50 dark:text-brand-100 dark:ring-brand-500"
                  : "border-navy-300 bg-white text-navy-700 hover:border-navy-400 hover:bg-navy-50 dark:border-navy-700 dark:bg-navy-950 dark:text-navy-300 dark:hover:bg-navy-800"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={value === option.value}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              {description ? (
                <>
                  <span className="min-w-0">
                    <span className="block font-medium">{option.label}</span>
                    <span className="mt-0.5 block text-xs text-navy-500 dark:text-navy-400">{description}</span>
                  </span>
                  <span
                    aria-hidden="true"
                    className={`grid size-5 shrink-0 place-items-center rounded-full border-2 ${
                      value === option.value ? "border-brand-600 dark:border-brand-400" : "border-navy-300 dark:border-navy-600"
                    }`}
                  >
                    {value === option.value && <span className="size-2.5 rounded-full bg-brand-600 dark:bg-brand-400" />}
                  </span>
                </>
              ) : (
                <span className="font-medium">{option.label}</span>
              )}
            </label>
          );
        })}
      </div>
      {hint && (
        <p id={hintId} className={hintClass}>
          {hint}
        </p>
      )}
    </fieldset>
  );
}

interface SelectProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
  describedBy?: string;
  children: ReactNode;
}

/** Native select (keeps keyboard and screen-reader behaviour) with the same look as the inputs. */
function Select({ id, value, onChange, invalid, describedBy, children }: SelectProps) {
  return (
    <div className="relative">
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className={`${controlClass} cursor-pointer appearance-none truncate pr-10`}
      >
        {children}
      </select>
      <svg
        viewBox="0 0 24 24"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-navy-500 dark:text-navy-400"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        aria-hidden="true"
      >
        <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

interface SettingRowProps {
  htmlFor: string;
  title: string;
  description: string;
  descriptionId?: string;
  disabled?: boolean;
  children: ReactNode;
}

/** A row with text on the left and its control on the right, used for both email options. */
function SettingRow({ htmlFor, title, description, descriptionId, disabled, children }: SettingRowProps) {
  return (
    <div className={`flex items-center justify-between gap-4 px-4 py-3.5 ${disabled ? "opacity-60" : ""}`}>
      <div className="min-w-0">
        <label htmlFor={htmlFor} className="block text-sm font-medium text-navy-900 dark:text-navy-100">
          {title}
        </label>
        <p id={descriptionId} className="mt-0.5 text-xs text-navy-500 dark:text-navy-400">
          {description}
        </p>
      </div>
      {children}
    </div>
  );
}

/**
 * Bell icon. Outline when not subscribed; when `ringing`, filled with sound waves
 * on both sides (the "subscribed / notifications on" look).
 */
export function BellGlyph({
  filled = false,
  ringing = false,
  className = "",
}: {
  filled?: boolean;
  ringing?: boolean;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" fill={filled || ringing ? "currentColor" : "none"} />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      {ringing && (
        <>
          <path d="M4 2C2.8 3.7 2 5.7 2 8" />
          <path d="M22 8c0-2.3-.8-4.3-2-6" />
        </>
      )}
    </svg>
  );
}

/**
 * Research subscriptions: settings stored on the server (/api/subscriptions).
 *
 * Subscriptions are saved to the user's account, but NOTHING is delivered on
 * their schedule yet. "Automatic email" is a stored preference until a
 * scheduler exists (Step D; the API always reports delivery_active=false).
 * Manual one-off test emails (Step C) are sent from the account page.
 */

import type { SubscriptionApi, SubscriptionInput, SummaryLevel } from "./api/types";
import type { Option } from "./filters";

export type Frequency = "daily" | "weekly" | "monthly";

export interface SubscriptionSettings {
  topic: string;
  frequency: Frequency;
  /** 0 = Sunday … 6 = Saturday. Used when frequency is "weekly". */
  weekday: number;
  /** 1-28 (so every month has it). Used when frequency is "monthly". */
  monthDay: number;
  /** 24-hour "HH:MM" in `timeZone`. */
  deliveryTime: string;
  /** IANA time zone, e.g. "America/New_York". */
  timeZone: string;
  paperCount: 5 | 10 | 15 | 20;
  readingLevel: SummaryLevel;
  emailWhenNoNewPapers: boolean;
  autoEmail: boolean;
}

/** A subscription as stored on the server, in the UI's shape. */
export interface Subscription extends SubscriptionSettings {
  id: string;
  createdAt: string;
  updatedAt: string;
  /** From the server; always false until delivery exists. */
  deliveryActive: boolean;
}

export const TOPIC_MIN_LENGTH = 2;
export const TOPIC_MAX_LENGTH = 200;

export const FREQUENCY_OPTIONS: Option<Frequency>[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

export const PAPER_COUNT_OPTIONS: Option<"5" | "10" | "15" | "20">[] = [
  { value: "5", label: "5" },
  { value: "10", label: "10" },
  { value: "15", label: "15" },
  { value: "20", label: "20" },
];

/** Subscription wording for the three existing summary levels. */
export const READING_LEVEL_OPTIONS: Option<SummaryLevel>[] = [
  { value: "high_school", label: "High School / General Reader" },
  { value: "college", label: "College / Undergraduate" },
  { value: "phd", label: "Researcher / Technical" },
];

/** One-line explanations shown under each reading-level choice. */
export const READING_LEVEL_DESCRIPTIONS: Record<SummaryLevel, string> = {
  high_school: "Plain language, terms explained",
  college: "Undergraduate-level science",
  phd: "Technical detail and methods critique",
};

export const WEEKDAYS =["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** All IANA time zones the browser knows, with UTC first. */
export function listTimeZones(): string[] {
  let zones: string[] = [];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  return ["UTC", ...zones.filter((zone) => zone !== "UTC")];
}

export function defaultSettings(topic: string, readingLevel: SummaryLevel): SubscriptionSettings {
  return {
    topic: topic.trim().slice(0, TOPIC_MAX_LENGTH),
    frequency: "weekly",
    weekday: 1, // Monday
    monthDay: 1,
    deliveryTime: "08:00",
    timeZone: browserTimeZone(),
    paperCount: 10,
    readingLevel,
    emailWhenNoNewPapers: false,
    autoEmail: true,
  };
}

/**
 * Topic key used to detect duplicates: case, accents, punctuation and spacing don't matter.
 * Must match the server's rule (backend app/services/text.normalize_title), which the
 * database's unique (user_id, topic_key) constraint enforces.
 */
export function topicKey(topic: string): string {
  return topic
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export type SettingsErrors = Partial<Record<"topic" | "weekday" | "monthDay" | "deliveryTime" | "timeZone", string>>;

export function validateSettings(settings: SubscriptionSettings, knownTimeZones: string[]): SettingsErrors {
  const errors: SettingsErrors = {};
  const topic = settings.topic.trim();
  if (topic.length < TOPIC_MIN_LENGTH) errors.topic = `Enter a topic of at least ${TOPIC_MIN_LENGTH} characters.`;
  else if (topic.length > TOPIC_MAX_LENGTH) errors.topic = `Keep the topic under ${TOPIC_MAX_LENGTH} characters.`;

  if (settings.frequency === "weekly" && !(settings.weekday >= 0 && settings.weekday <= 6)) {
    errors.weekday = "Choose a delivery day.";
  }
  if (settings.frequency === "monthly" && !(settings.monthDay >= 1 && settings.monthDay <= 28)) {
    errors.monthDay = "Choose a day from 1 to 28.";
  }
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(settings.deliveryTime)) {
    errors.deliveryTime = "Choose a delivery time.";
  }
  if (!knownTimeZones.includes(settings.timeZone)) errors.timeZone = "Choose a time zone from the list.";
  return errors;
}

/** Delivery times every 30 minutes, as "HH:MM" values with "8:00 AM"-style labels. */
export function deliveryTimeOptions(): Option<string>[] {
  return Array.from({ length: 48 }, (_, i) => {
    const value = `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`;
    return { value, label: formatTime(value) };
  });
}

/** "08:00" -> "8:00 AM" */
export function formatTime(time: string): string {
  const [hours, minutes] = time.split(":").map(Number);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return time;
  return new Date(Date.UTC(2000, 0, 1, hours, minutes)).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

function ordinal(day: number): string {
  const suffix = day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th";
  return `${day}${suffix}`;
}

/** "Weekly on Monday at 8:00 AM (America/New_York)" */
export function describeSchedule(settings: SubscriptionSettings): string {
  const when =
    settings.frequency === "daily"
      ? "Daily"
      : settings.frequency === "weekly"
        ? `Weekly on ${WEEKDAYS[settings.weekday]}`
        : `Monthly on the ${ordinal(settings.monthDay)}`;
  return `${when} at ${formatTime(settings.deliveryTime)} (${settings.timeZone.replace(/_/g, " ")})`;
}

/** UI settings -> API body. Days the frequency doesn't use are sent as null. */
export function toSubscriptionInput(settings: SubscriptionSettings): SubscriptionInput {
  return {
    topic: settings.topic.trim(),
    frequency: settings.frequency,
    weekday: settings.frequency === "weekly" ? settings.weekday : null,
    month_day: settings.frequency === "monthly" ? settings.monthDay : null,
    delivery_time: settings.deliveryTime,
    time_zone: settings.timeZone,
    paper_count: settings.paperCount,
    reading_level: settings.readingLevel,
    email_enabled: settings.autoEmail,
    email_when_no_new_papers: settings.emailWhenNoNewPapers,
  };
}

/** API record -> UI shape. Unused days get sensible defaults so switching frequency in the form works. */
export function fromSubscriptionApi(api: SubscriptionApi): Subscription {
  return {
    id: api.id,
    topic: api.topic,
    frequency: api.frequency,
    weekday: api.weekday ?? 1,
    monthDay: api.month_day ?? 1,
    deliveryTime: api.delivery_time,
    timeZone: api.time_zone,
    paperCount: api.paper_count,
    readingLevel: api.reading_level,
    emailWhenNoNewPapers: api.email_when_no_new_papers,
    autoEmail: api.email_enabled,
    deliveryActive: api.delivery_active,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  };
}

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const dayTimeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});
const fullFmt = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export const localTzName =
  new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName")?.value ?? "local";

export const fmtTime = (iso: string | Date) => timeFmt.format(new Date(iso));
export const fmtDayTime = (iso: string | Date) => dayTimeFmt.format(new Date(iso));
export const fmtFull = (iso: string | Date) => fullFmt.format(new Date(iso));

export function fmtDuration(hours: number): string {
  const total = Math.round(hours * 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export const fmtMiles = (mi: number) =>
  mi >= 100 ? `${Math.round(mi).toLocaleString()} mi` : `${mi.toFixed(mi < 10 ? 1 : 0)} mi`;

export const fmtLb = (lb: number) => `${Math.round(lb).toLocaleString()} lb`;

/** Value for an <input type="datetime-local"> in the browser's timezone. */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function nextHour(): Date {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return d;
}

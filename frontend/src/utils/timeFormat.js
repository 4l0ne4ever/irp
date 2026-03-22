/**
 * Decimal hours within a planning day → HH:MM (24h).
 */
export function formatDayHour(h) {
  if (h == null || Number.isNaN(Number(h))) return "—";
  let totalMin = Math.round(Number(h) * 60);
  totalMin = Math.max(0, totalMin);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

/**
 * Decimal hours (solver clock) → HH:MM:SS on a 24h dial, synced with simulation time.
 */
export function formatSimClock24(h) {
  if (h == null || Number.isNaN(Number(h))) return "—";
  const x = Math.max(0, Math.min(24 - 1e-9, Number(h)));
  const totalSec = Math.min(24 * 3600 - 1, Math.max(0, Math.round(x * 3600)));
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

/** Giờ mô phỏng không giới hạn 24h (timeline nối nhiều xe / offset). */
export function formatSimTimelineClock(h) {
  if (h == null || Number.isNaN(Number(h))) return "—";
  const x = Math.max(0, Number(h));
  const totalSec = Math.max(0, Math.round(x * 3600));
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  return `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function clamp01(x) {
  return Math.min(1, Math.max(0, x));
}

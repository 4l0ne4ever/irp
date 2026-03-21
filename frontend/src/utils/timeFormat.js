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

export function clamp01(x) {
  return Math.min(1, Math.max(0, x));
}

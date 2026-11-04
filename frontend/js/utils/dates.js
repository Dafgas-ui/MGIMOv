// Calendar-key and interval ideas extracted without DOM, storage or app globals.
export function calendarKey(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) throw new TypeError('Invalid date');
  return `${String(date.getFullYear()).padStart(4, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function parseDate(key) {
  if (typeof key !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(key)) throw new TypeError('Invalid date key');
  const date = new Date(`${key}T12:00:00`);
  if (Number.isNaN(date.getTime()) || calendarKey(date) !== key) throw new TypeError('Invalid calendar date');
  return date;
}
export function addDays(key, amount) {
  if (!Number.isInteger(amount)) throw new TypeError('Integer day offset required');
  const date = parseDate(key);
  date.setDate(date.getDate() + amount);
  return calendarKey(date);
}
export function weekDates(key) {
  const date = parseDate(key);
  const monday = addDays(key, -((date.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, index) => addDays(monday, index));
}
function minutes(value, end = false) {
  if (end && value === '24:00') return 1440;
  if (typeof value !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) throw new TypeError('Invalid time');
  const [hours, minutes] = value.split(':').map(Number);
  return hours * 60 + minutes;
}
export function overlaps(first, second) {
  const interval = item => {
    parseDate(item.date);
    const start = minutes(item.start), end = minutes(item.end, true);
    if (start >= end) throw new TypeError('Invalid interval');
    return { start, end };
  };
  const a = interval(first), b = interval(second);
  return first.date === second.date && a.start < b.end && b.start < a.end;
}

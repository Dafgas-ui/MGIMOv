import test from 'node:test';
import assert from 'node:assert/strict';
import { calendarKey, parseDate, addDays, weekDates, overlaps } from '../frontend/js/utils/dates.js';
test('calendar dates preserve leap days and reject normalized invalid dates', () => {
  assert.equal(calendarKey(parseDate('2028-02-29')), '2028-02-29');
  for (const value of ['2026-02-29', '2026-13-01', 'bad', '2026-11-31']) assert.throws(() => parseDate(value));
  assert.throws(() => calendarKey(new Date('invalid')));
});
test('day arithmetic crosses month and year boundaries', () => {
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(addDays('2028-03-01', -1), '2028-02-29');
  assert.throws(() => addDays('2026-11-04', .5));
});
test('week starts Monday including Sundays and year boundaries', () => {
  assert.deepEqual(weekDates('2027-01-03'), ['2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02','2027-01-03']);
});
test('overlaps preserve distinct days and touching boundaries', () => {
  const event = (start, end, date = '2026-11-04') => ({date, start, end});
  assert.equal(overlaps(event('09:00','10:00'),event('10:00','11:00')), false);
  assert.equal(overlaps(event('09:00','10:30'),event('10:00','11:00')), true);
  assert.equal(overlaps(event('09:00','10:30'),event('09:00','10:30','2026-11-05')), false);
  assert.equal(overlaps(event('23:00','24:00'),event('23:30','24:00')), true);
  assert.throws(() => overlaps(event('12:00','11:00'),event('10:00','11:00')));
  assert.throws(() => overlaps(event('24:00','24:00'),event('10:00','11:00')));
});

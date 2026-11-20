/** Read-only simulation of the authoritative forecast contract. No I/O. */
export function sanitizeSimulationPoints(value, maximum) {
  if (value === '' || value === null || value === undefined) return null;
  if (typeof value !== 'number' && typeof value !== 'string') throw new RangeError('invalid_points');
  if (typeof value === 'string' && !/^[0-9]+$/.test(value)) throw new RangeError('invalid_points');
  const points = Number(value);
  if (!Number.isSafeInteger(points) || points < 0 || points > maximum) throw new RangeError('invalid_points');
  return points;
}

function validContract(course) {
  const integer = (value, maximum) => Number.isSafeInteger(value) && value >= 0 && value <= maximum;
  if (course.plan_maximum !== 100 || !integer(course.admission_minimum, 100) || course.admission_minimum < 50
      || !['exam', 'credit', 'graded_credit'].includes(course.control)
      || !Array.isArray(course.categories) || !Array.isArray(course.events) || !course.events.length
      || course.categories.map(c => c.maximum).sort((a,b) => a-b).join(',') !== '20,20,20,40') return false;
  const categories = new Map();
  for (const category of course.categories) {
    if (!category.code || categories.has(category.code) || !integer(category.admission_min, category.maximum)) return false;
    categories.set(category.code, category);
  }
  const codes = new Set(), maxima = new Map(), published = new Map();
  for (const event of course.events) {
    if (!event.code || codes.has(event.code) || !categories.has(event.category_code)
        || !integer(event.maximum, 100) || event.maximum === 0 || typeof event.required !== 'boolean'
        || !integer(event.admission_min, event.maximum)
        || (event.points !== null && !integer(event.points, event.maximum))) return false;
    codes.add(event.code);
    maxima.set(event.category_code, (maxima.get(event.category_code) || 0) + event.maximum);
    published.set(event.category_code, (published.get(event.category_code) || 0) + (event.points ?? 0));
  }
  for (const [code, category] of categories) {
    if ((maxima.get(code) || 0) > category.maximum || (published.get(code) || 0) > category.maximum) return false;
  }
  if (course.control === 'graded_credit') {
    if (!Array.isArray(course.scale) || !course.scale.length) return false;
    const minima = new Set();
    for (const row of course.scale) {
      if (!integer(row.minimum, 100) || minima.has(row.minimum) || !/^[2-5]$/.test(String(row.outcome))) return false;
      minima.add(row.minimum);
    }
  }
  return true;
}

export function simulateCourseBrs(course, userInputs = {}) {
  if (!course?.available) return {available:false, reason:course?.reason || 'unavailable'};
  if (!validContract(course)) return {available:false, reason:'incomplete_contract'};
  if (Object.keys(userInputs).some(code => !course.events.some(event => event.code === code)))
    return {available:false, reason:'invalid_points'};
  const events = [];
  for (const event of course.events) {
    let input;
    try { input = sanitizeSimulationPoints(userInputs[event.code], event.maximum); }
    catch { return {available:false, reason:'invalid_points'}; }
    events.push({...event, actualPoints:event.points, simulatedPoints:input ?? event.points,
      isHypothetical:input !== null, categoryCode:event.category_code});
  }
  const hasHypothetical = events.some(event => event.isHypothetical);
  const hasData = events.some(event => event.simulatedPoints !== null);
  const categories = course.categories.map(category => ({...category, actualPoints:category.points,
    simulatedPoints:events.filter(event => event.category_code === category.code)
      .reduce((sum,event) => sum + (event.simulatedPoints ?? 0), 0)}));
  if (categories.some(category => category.simulatedPoints > category.maximum))
    return {available:false, reason:'invalid_points'};
  const missingRequired = events.filter(event => event.required &&
    (event.simulatedPoints === null || event.simulatedPoints < event.admission_min)).map(event => event.code);
  const categoryShortfalls = categories.filter(category => category.simulatedPoints < category.admission_min).map(category => category.code);
  const simulatedTotal = hasData ? categories.reduce((sum,category) => sum + category.simulatedPoints, 0) : null;
  const admitted = hasData ? simulatedTotal >= course.admission_minimum && !missingRequired.length && !categoryShortfalls.length : null;
  const complete = events.every(event => event.simulatedPoints !== null);
  let outcome = null, grade = null;
  if (hasData && course.control === 'exam') outcome = admitted ? 'admitted' : 'not_admitted';
  if (complete && course.control === 'credit') outcome = simulatedTotal >= 50 ? 'pass' : 'fail';
  if (complete && course.control === 'graded_credit') {
    const match = [...course.scale].sort((a,b) => b.minimum-a.minimum).find(row => simulatedTotal >= row.minimum);
    if (match) { grade = Number(match.outcome); outcome = 'graded'; }
  }
  return {available:true, courseId:course.id, control:course.control, planMaximum:100,
    hasHypothetical, hasData, complete, simulatedTotal, publishedTotal:course.published_points,
    admissionMinimum:course.admission_minimum, admitted, missingRequired, categoryShortfalls,
    outcome, grade, events, categories};
}

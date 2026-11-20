import {t} from './language.js';
import {simulateCourseBrs} from './brs-calculator-state.js';

export function calculatorExplanation(sim) {
  if (sim.control === 'exam') return sim.admitted
    ? t(`Условия допуска выполнены. Порог: ${sim.admissionMinimum}.`,
        `Admission requirements met. Threshold: ${sim.admissionMinimum}.`)
    : t(`Условия допуска не выполнены. Порог: ${sim.admissionMinimum}.`,
        `Admission requirements not met. Threshold: ${sim.admissionMinimum}.`);
  if (!sim.complete) return t('Есть мероприятия без результата. Итог пока не рассчитан.',
    'Some events have no result. A final outcome cannot be calculated yet.');
  if (sim.control === 'credit') return sim.outcome === 'pass'
    ? t('Смоделированный результат: зачтено.', 'Simulated outcome: pass.')
    : t('Смоделированный результат: не зачтено.', 'Simulated outcome: fail.');
  return sim.grade === null
    ? t('Шкала не определяет результат для этих баллов.', 'The scale has no outcome for these points.')
    : t(`Смоделированная оценка: ${sim.grade}.`, `Simulated grade: ${sim.grade}.`);
}

export function renderCalculator(document, card, course) {
  if (!course || !course.available) return;

  const node = (tag, text) => {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    return el;
  };

  const section = node('details');
  section.className = 'brs-calculator-details';

  const summary = node('summary', t('Моделирование баллов («Что, если?»)', 'Score Simulation ("What If?")'));
  summary.className = 'brs-calculator-summary';
  section.append(summary);

  const container = node('div');
  container.className = 'brs-calculator-container';

  const disclaimer = node('p', t(
    'Симуляция для предварительной оценки. Не является официальным прогнозом или изменением данных в системе. Все расчеты производятся локально.',
    'Simulation for preliminary assessment. Not an official prediction or database change. All calculations are performed locally.'
  ));
  disclaimer.className = 'brs-calculator-disclaimer';
  container.append(disclaimer);

  const inputsContainer = node('div');
  inputsContainer.className = 'brs-calculator-inputs';

  const userInputs = {};
  const inputElements = new Map();

  const resultsBox = node('div');
  resultsBox.className = 'brs-calculator-results';
  resultsBox.setAttribute?.('aria-live', 'polite');

  function updateSimulation() {
    const sim = simulateCourseBrs(course, userInputs);
    resultsBox.replaceChildren();
    resultsBox.append(node('h5', t('Результаты симуляции', 'Simulation results')));
    if (!sim.available) {
      resultsBox.append(node('p', sim.reason === 'invalid_points'
        ? t('Введите целое число от 0 до максимума мероприятия.', 'Enter an integer from 0 to the event maximum.')
        : t('Недостаточно правил плана для достоверного расчёта. Обновите прогноз.',
            'Plan rules are incomplete. Refresh the forecast before calculating.')));
      return;
    }
    if (!sim.hasData) {
      resultsBox.append(node('p', t('Опубликованных результатов нет. Введите баллы для сценария.',
        'No published results. Enter points to create a scenario.')));
      return;
    }
    const total = node('p');
    total.className = 'brs-sim-total';
    total.textContent = sim.hasHypothetical
      ? t(`Сценарий: ${sim.simulatedTotal} из 100.`, `Scenario: ${sim.simulatedTotal} of 100.`)
      : t(`Опубликовано: ${sim.simulatedTotal} из 100.`, `Published: ${sim.simulatedTotal} of 100.`);
    resultsBox.append(total);
    resultsBox.append(node('p', course.published_points === null
      ? t('Фактических опубликованных баллов пока нет.', 'There are no actual published points yet.')
      : t(`Фактические опубликованные баллы: ${course.published_points}.`,
          `Actual published points: ${course.published_points}.`)));
    resultsBox.append(node('p', calculatorExplanation(sim)));
    if (sim.missingRequired.length || sim.categoryShortfalls.length) {
      resultsBox.append(node('p', t('Не выполнены обязательные мероприятия или минимумы категорий.',
        'Required events or category minima are not satisfied.')));
    }
    if (course.control === 'exam') {
      const notice = node('p', t('Экзаменационную оценку выставляет экзаменатор.',
        'The examiner determines the exam grade.'));
      notice.className = 'brs-exam-examiner-notice';
      resultsBox.append(notice);
    }
  }

  for (const event of course.events || []) {
    const row = node('div');
    row.className = 'brs-calculator-row';

    const label = node('label');
    label.className = 'brs-calculator-label';
    const publishedNote = event.points !== null ? ` (${t('факт', 'actual')}: ${event.points})` : ` (${t('не сдано', 'unrated')})`;
    label.textContent = `${event.title}${publishedNote} [${t('максимум', 'maximum')}: ${event.maximum}]: `;

    const input = node('input');
    input.type = 'number';
    input.min = '0';
    input.max = String(event.maximum);
    input.step = '1';
    input.className = 'brs-calculator-input';
    input.placeholder = event.points !== null ? String(event.points) : '—';
    input.setAttribute?.('aria-label', `${event.title} (${t('максимум', 'maximum')} ${event.maximum})`);

    const onInput = () => {
      userInputs[event.code] = input.value;
      if (input.value !== '') {
        input.classList?.add('brs-input-hypothetical');
      } else {
        input.classList?.remove('brs-input-hypothetical');
      }
      updateSimulation();
    };

    if (typeof input.addEventListener === 'function') {
      input.addEventListener('input', onInput);
    }

    label.append(input);
    row.append(label);
    inputsContainer.append(row);
    inputElements.set(event.code, input);
  }

  const actions = node('div');
  actions.className = 'brs-calculator-actions';

  const resetBtn = node('button', t('Сбросить симуляцию', 'Reset simulation'));
  resetBtn.type = 'button';
  resetBtn.className = 'brs-calculator-reset';

  const onReset = () => {
    for (const [code, input] of inputElements.entries()) {
      input.value = '';
      input.classList?.remove('brs-input-hypothetical');
      delete userInputs[code];
    }
    updateSimulation();
  };

  if (typeof resetBtn.addEventListener === 'function') {
    resetBtn.addEventListener('click', onReset);
  }

  actions.append(resetBtn);
  container.append(inputsContainer, actions, resultsBox);
  section.append(container);
  card.append(section);

  updateSimulation();
}

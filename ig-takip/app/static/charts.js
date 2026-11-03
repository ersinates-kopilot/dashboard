// Dashboard grafikleri. Renkler CSS değişkenlerinden okunur (açık/koyu tema otomatik).
(function () {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (n, d = 0) => n == null ? '—' : n.toLocaleString('tr-TR', { minimumFractionDigits: d, maximumFractionDigits: d });

  function base() {
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: css('--surface'), titleColor: css('--text'), bodyColor: css('--text-2'),
                   borderColor: css('--border'), borderWidth: 1, padding: 10, boxPadding: 4 },
      },
      scales: {
        x: { grid: { display: false }, border: { color: css('--border') }, ticks: { color: css('--text-3'), maxRotation: 0, autoSkipPadding: 16 } },
        y: { grid: { color: css('--grid') }, border: { display: false }, ticks: { color: css('--text-3') } },
      },
    };
  }

  function line(el, d) {
    const o = base();
    o.scales.y.ticks.callback = (v) => fmt(v);
    o.plugins.tooltip.callbacks = { label: (c) => ` ${el.dataset.label}: ${fmt(c.parsed.y)}` };
    new Chart(el, { type: 'line', options: o, data: { labels: d.labels, datasets: [{
      data: d.values, borderColor: css('--s1'), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
      pointHoverBackgroundColor: css('--s1'), pointHoverBorderColor: css('--surface'), pointHoverBorderWidth: 2, tension: 0.25,
    }] } });
  }

  function bar(el, d) {
    const o = base();
    o.interaction = { mode: 'nearest', intersect: false, axis: 'x' };
    o.scales.y.ticks.callback = (v) => '%' + fmt(v, 1);
    o.plugins.tooltip.callbacks = {
      label: (c) => ` Etkileşim: %${fmt(c.parsed.y, 2)}`,
      afterLabel: (c) => d.captions[c.dataIndex] ? ' ' + d.captions[c.dataIndex] : '',
    };
    new Chart(el, { type: 'bar', options: o, data: { labels: d.labels, datasets: [{
      data: d.values, backgroundColor: css('--s1'), borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: 'bottom',
      maxBarThickness: 18, categoryPercentage: 0.8, barPercentage: 0.9,
    }] } });
  }

  function multi(el, series) {
    const slots = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
    const o = base();
    o.scales.x = { ...o.scales.x, type: 'time', time: { unit: 'week', tooltipFormat: 'dd.MM.yyyy', displayFormats: { week: 'dd.MM', day: 'dd.MM' } } };
    o.scales.y.ticks.callback = (v) => (v > 0 ? '+' : '') + fmt(v, 1) + '%';
    o.plugins.legend = { display: true, position: 'top', align: 'start',
      labels: { color: css('--text-2'), usePointStyle: true, pointStyle: 'line', boxWidth: 18 } };
    o.plugins.tooltip.callbacks = {
      label: (c) => ` ${c.dataset.label}: ${(c.parsed.y > 0 ? '+' : '') + fmt(c.parsed.y, 2)}% (${fmt(c.raw.raw)} takipçi)`,
    };
    new Chart(el, { type: 'line', options: o, data: { datasets: series.map((s, i) => ({
      label: s.name, data: s.points, borderColor: css(slots[i % 8]), backgroundColor: css(slots[i % 8]),
      borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHoverBorderColor: css('--surface'), pointHoverBorderWidth: 2, tension: 0.25,
    })) } });
  }

  window.addEventListener('DOMContentLoaded', () => {
    if (!window.Chart) return;
    document.querySelectorAll('canvas[data-chart]').forEach((el) => {
      const d = JSON.parse(el.dataset.json);
      ({ line, bar, multi })[el.dataset.chart](el, d);
    });
  });
})();

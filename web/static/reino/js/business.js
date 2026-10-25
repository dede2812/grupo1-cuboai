/* Local SVG chart: no third-party script, tracking, or invented series. */
(() => {
  'use strict';
  const source = document.getElementById('bi-chart-data');
  const host = document.getElementById('bi-chart');
  const control = document.getElementById('bi-metric');
  const tooltip = document.getElementById('bi-tooltip');
  if (!source || !host || !control) return;
  const data = JSON.parse(source.textContent);
  const ns = 'http://www.w3.org/2000/svg';
  const money = new Intl.NumberFormat('es-SV', {style: 'currency', currency: data.currency});
  const number = new Intl.NumberFormat('es-SV', {maximumFractionDigits: 0});
  function el(tag, attrs = {}, text = '') {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    return node;
  }
  function draw() {
    const metric = control.value;
    const format = value => value === null ? 'Sin datos suficientes' : metric === 'orders' ? number.format(value) : money.format(value);
    const width = 880, height = 260, left = 76, right = 18, top = 20, bottom = 38;
    const allValues = [...data.current, ...data.previous].map(row => row[metric]).filter(value => value !== null);
    const high = Math.max(1, ...allValues), low = Math.min(0, ...allValues);
    const count = Math.max(data.current.length, data.previous.length, 2);
    const x = index => left + index / (count - 1) * (width - left - right);
    const y = value => top + (high - value) / (high - low) * (height - top - bottom);
    const svg = el('svg', {viewBox: `0 0 ${width} ${height}`, 'aria-label': control.options[control.selectedIndex].text});
    for (let index = 0; index <= 4; index++) {
      const value = low + (high - low) * index / 4;
      svg.append(el('line', {x1: left, x2: width - right, y1: y(value), y2: y(value), stroke: '#e4e9ef', 'stroke-width': 1}));
      svg.append(el('text', {x: left - 10, y: y(value) + 4, 'text-anchor': 'end'}, format(value)));
    }
    [['previous', '#a3aebb', 'Período anterior'], ['current', '#366a91', 'Período actual']].forEach(([key, color, label]) => {
      const series = data[key];
      let segment = [];
      function appendSegment() {
        if (segment.length) svg.append(el('polyline', {points: segment.join(' '), fill: 'none', stroke: color, 'stroke-width': key === 'current' ? 3 : 2, 'stroke-dasharray': key === 'previous' ? '5 5' : 'none'}));
        segment = [];
      }
      series.forEach((point, index) => {
        if (point[metric] === null) appendSegment();
        else segment.push(`${x(index)},${y(point[metric])}`);
      });
      appendSegment();
      series.forEach((point, index) => {
        if (point[metric] === null) return;
        const description = `${label} · ${point.label} · ${format(point[metric])}`;
        const circle = el('circle', {cx: x(index), cy: y(point[metric]), r: series.length > 60 ? 2 : 3.5, fill: color, tabindex: 0, role: 'img', 'aria-label': description});
        circle.append(el('title', {}, description));
        circle.addEventListener('focus', () => { tooltip.textContent = description; });
        circle.addEventListener('pointerenter', () => { tooltip.textContent = description; });
        circle.addEventListener('click', () => { tooltip.textContent = description; });
        svg.append(circle);
      });
    });
    const stride = Math.max(1, Math.ceil(data.current.length / 5));
    data.current.forEach((point, index) => {
      if (index % stride === 0 || index === data.current.length - 1) {
        svg.append(el('text', {x: x(index), y: height - 10, 'text-anchor': index === 0 ? 'start' : 'end'}, point.label.slice(5)));
      }
    });
    host.replaceChildren(svg);
  }
  control.addEventListener('change', draw);
  draw();
})();

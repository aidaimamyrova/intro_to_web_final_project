/* ─── Live Clock ─────────────────────────────────────────── */
function updateClock() {
  const el = document.getElementById('live-time');
  if (!el) return;
  const now = new Date();
  el.textContent = now.toLocaleTimeString('en-US', { hour12: false });
}
updateClock();
setInterval(updateClock, 1000);

/* ─── Flash Auto-dismiss ─────────────────────────────────── */
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => el.style.opacity = '0', 4000);
  setTimeout(() => el.remove(), 4500);
});

/* ─── Bar Chart (Canvas, no library) ────────────────────── */
function drawBarChart(canvasId, labels, values) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const W = rect.width;
  const H = rect.height || 200;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);

  const maxVal = Math.max(...values, 1);
  const pad    = { top: 20, right: 20, bottom: 40, left: 60 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;
  const barW   = Math.floor(chartW / values.length * 0.6);
  const gap    = chartW / values.length;

  // Grid lines
  ctx.strokeStyle = 'rgba(42,42,53,0.8)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + chartW, y);
    ctx.stroke();
    // Y-axis label
    const val = Math.round(maxVal - (maxVal / 4) * i);
    ctx.fillStyle = 'rgba(90,90,112,0.9)';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textAlign = 'right';
    ctx.fillText('$' + val, pad.left - 8, y + 4);
  }

  // Bars
  values.forEach((val, i) => {
    const barH = (val / maxVal) * chartH;
    const x = pad.left + gap * i + (gap - barW) / 2;
    const y = pad.top + chartH - barH;

    // Gradient
    const grad = ctx.createLinearGradient(0, y, 0, y + barH);
    grad.addColorStop(0, 'rgba(200,245,66,0.9)');
    grad.addColorStop(1, 'rgba(200,245,66,0.2)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, [3, 3, 0, 0]);
    ctx.fill();

    // Value label on bar
    if (val > 0) {
      ctx.fillStyle = 'rgba(200,245,66,0.9)';
      ctx.font = '10px JetBrains Mono, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('$' + Math.round(val), x + barW / 2, y - 6);
    }

    // X-axis label
    ctx.fillStyle = 'rgba(90,90,112,0.9)';
    ctx.font = '11px DM Sans, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(labels[i] || '', x + barW / 2, pad.top + chartH + 20);
  });
}

/* ─── Animate stat numbers ───────────────────────────────── */
document.querySelectorAll('.stat-value').forEach(el => {
  const rawText = el.textContent.trim();
  const num = parseFloat(rawText.replace(/[^0-9.]/g, ''));
  if (isNaN(num) || num === 0) return;
  const prefix = rawText.startsWith('$') ? '$' : '';
  const isFloat = rawText.includes('.');
  let start = null;
  const duration = 800;
  function step(ts) {
    if (!start) start = ts;
    const progress = Math.min((ts - start) / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3);
    const current = num * ease;
    el.textContent = prefix + (isFloat ? current.toFixed(0) : Math.round(current));
    if (progress < 1) requestAnimationFrame(step);
    else el.textContent = rawText; // restore exact value
  }
  requestAnimationFrame(step);
});

/* ─── Confirm delete buttons ─────────────────────────────── */
document.querySelectorAll('[data-confirm]').forEach(btn => {
  btn.addEventListener('click', e => {
    if (!confirm(btn.dataset.confirm)) e.preventDefault();
  });
});

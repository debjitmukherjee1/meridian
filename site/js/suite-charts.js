/* suite-charts.js — Chart.js defaults for the dark suite theme.
   Loaded right after vendor/chart.umd.min.js, before the app's own scripts. */
(function () {
  if (!window.Chart) return;
  var d = Chart.defaults;
  d.font.family = '"Geist Mono", ui-monospace, "SF Mono", Menlo, monospace';
  d.font.size = 12;
  d.color = "#8f9199";
  d.borderColor = "rgba(255,255,255,.07)";
  var t = d.plugins.tooltip;
  t.backgroundColor = "rgba(18,18,20,.94)";
  t.borderColor = "rgba(255,255,255,.16)";
  t.borderWidth = 1;
  t.titleColor = "#f3f3f1";
  t.bodyColor = "#a8aab0";
  t.titleFont = { family: '"Geist", ui-sans-serif, system-ui, sans-serif', weight: "500", size: 13 };
  t.bodyFont = { family: '"Geist Mono", ui-monospace, monospace', size: 12 };
  t.padding = 12;
  t.cornerRadius = 12;
  t.boxPadding = 5;
  t.usePointStyle = true;
  d.plugins.legend.labels.color = "#a8aab0";
})();

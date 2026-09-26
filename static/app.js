const $ = (id) => document.getElementById(id);
const percent = (n) => (100 * n).toFixed(1) + "%";
function el(tag, text, cls) {
  const n = document.createElement(tag);
  n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
async function get(path) {
  const r = await fetch("/api/" + path);
  const d = await r.json();
  if (!r.ok) throw Error(d.detail || "Could not load analysis.");
  return d;
}
function error(e) {
  $("error").textContent = e.message;
  $("error").classList.remove("hidden");
}
function bars(id, data, label, value, suffix, max) {
  $(id).replaceChildren(
    ...data.map((d) => {
      const n = document.createElement("div");
      n.append(el("strong", `${d[label]} · ${d[value]}${suffix}`));
      const track = el("div", "", "bar-track"),
        bar = el("div", "", "bar");
      bar.style.width = (100 * d[value]) / max + "%";
      track.append(bar);
      n.append(
        track,
        el("p", d.attended === undefined ? `${d.appointments.toLocaleString()} appointments` : `${d.attended.toLocaleString()} attended visits`, "muted"),
      );
      return n;
    }),
  );
}
let recordVersion = 0;
async function records() {
  const version = ++recordVersion;
  const params = new URLSearchParams({
    provider: $("provider").value,
    appointment_type: $("type").value,
  });
  const d = await get("appointments?" + params),
    s = d.summary;
  if (version !== recordVersion) return;
  $("cohort").textContent =
    `${s.appointments.toLocaleString()} appointments · ${s.no_show_rate === null ? "—" : percent(s.no_show_rate)} no-shows · ${s.mean_wait_minutes === null ? "—" : s.mean_wait_minutes.toFixed(1)} min mean attended wait`;
  $("records").replaceChildren(
    ...d.rows.map((r) => {
      const tr = document.createElement("tr");
      [
        r.appointment_id,
        r.appointment_date,
        r.provider,
        r.appointment_type,
        r.age_group,
        r.no_show ? "Yes" : "No",
        r.wait_minutes ?? "—",
      ].forEach((v) => tr.append(el("td", String(v))));
      return tr;
    }),
  );
}
async function start() {
  const r = await get("report");
  $("appointments").textContent = r.summary.appointments.toLocaleString();
  $("no-shows").textContent = percent(r.summary.no_show_rate);
  $("wait").textContent = r.summary.mean_wait_minutes + " min";
  bars("types", r.by_type, "appointment_type", "no_show_percent", "%", 40);
  bars(
    "providers",
    r.by_provider,
    "provider",
    "average_wait_minutes",
    " min",
    35,
  );
  $("findings").replaceChildren(
    ...r.findings.map((f) => el("p", f, "finding")),
  );
  const q = r.quality;
  $("quality").replaceChildren(
    el(
      "p",
      `${q.input_rows.toLocaleString()} raw rows → ${q.accepted_rows.toLocaleString()} validated rows`,
    ),
    el(
      "p",
      `${q.quarantined_rows} quarantined · ${q.duplicate_rows} duplicate IDs · ${q.unknown_age_rows} unknown age group`,
    ),
  );
  const m = r.model;
  renderOperations(m);
  $("model").replaceChildren(
    el(
      "p",
      `Holdout ROC-AUC: ${m.model_metrics.roc_auc} · Baseline: ${m.baseline_metrics.roc_auc}`,
    ),
    el(
      "p",
      `Average precision: ${m.model_metrics.average_precision} · Baseline: ${m.baseline_metrics.average_precision}`,
    ),
    el(
      "p",
      `Brier score: ${m.model_metrics.brier_score} · Baseline: ${m.baseline_metrics.brier_score}`,
    ),
    el(
      "p",
      `Reminder-review precision: ${percent(m.precision)} · Recall: ${percent(m.recall)}`,
    ),
    el(
      "p",
      `${m.split.test.rows} holdout visits · ${percent(m.flagged_fraction)} flagged`,
    ),
  );
  $("limitations").replaceChildren(
    ...m.limitations.map((l) => el("p", l, "muted")),
  );
  $("groups").replaceChildren(
    ...m.age_group_audit.map((g) =>
      el(
        "p",
        `${g.age_group}: n=${g.rows}; observed ${percent(g.observed_rate)}, mean predicted ${percent(g.mean_predicted)}`,
        "muted",
      ),
    ),
  );
  r.by_provider.forEach((p) => {
    const o = el("option", p.provider);
    o.value = p.provider;
    $("provider").append(o);
  });
  r.by_type.forEach((t) => {
    const o = el("option", t.appointment_type);
    o.value = t.appointment_type;
    $("type").append(o);
  });
  await records();
}
$("provider").onchange = () => records().catch(error);
$("type").onchange = () => records().catch(error);
start().catch(error);

function svgNode(tag, attributes = {}, text = "") {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) n.setAttribute(key, value);
  if (text) n.textContent = text;
  return n;
}
function chartFrame(label) {
  const svg = svgNode("svg", {viewBox: "0 0 520 275", role: "img", class: "chart", "aria-label": label});
  svg.append(svgNode("title", {}, label));
  return svg;
}
function renderOperations(model) {
  const data = model.operations;
  function capacity() {
    const r = data.capacity_scenarios.find(row => row.capacity_percent === Number($("capacity").value));
    const cards = [
      ["REVIEW SLOTS", r.slots, `${r.cohort_size} holdout visits`],
      ["NO-SHOWS IN QUEUE", r.captured_no_shows, `${percent(r.recall)} of all holdout no-shows`],
      ["QUEUE PRECISION", percent(r.precision), "Observed no-shows ÷ selected visits"],
      ["LIFT VS RANDOM", r.lift_over_random === null ? "—" : r.lift_over_random.toFixed(2) + "×", `Random expectation: ${r.random_expected_captured.toFixed(1)} no-shows`],
    ];
    $("capacity-results").replaceChildren(...cards.map(([label, value, note]) => {
      const n = el("div", label, "capacity-result");
      n.append(el("strong", String(value)), el("small", note));
      return n;
    }));
  }
  $("capacity").onchange = capacity;
  capacity();
  $("capacity-method").textContent = data.capacity_method;
  const curve = chartFrame("Validation precision and recall versus probability threshold, from zero to one");
  const x = v => 45 + v * 450, y = v => 220 - v * 180;
  for (const value of [0, .25, .5, .75, 1]) {
    curve.append(svgNode("line", {x1:45, x2:495, y1:y(value), y2:y(value), class:"gridline"}), svgNode("text", {x:35,y:y(value)+4,"text-anchor":"end"},String(value)),svgNode("text", {x:x(value),y:241,"text-anchor":"middle"},String(value)));
  }
  for (const metric of ["precision", "recall"]) curve.append(svgNode("polyline", {points:data.validation_curve.map(r => `${x(r.threshold)},${y(r[metric])}`).join(" "),class:metric}));
  curve.append(svgNode("line", {x1:x(model.threshold),x2:x(model.threshold),y1:30,y2:220,stroke:"#b6c8d2","stroke-dasharray":"4 4"}),svgNode("text", {x:270,y:266,"text-anchor":"middle"},"Probability threshold"));
  const legend = el("div", "", "legend"); legend.append(el("span", "Precision"),el("span", "Recall"));
  $("threshold-chart").replaceChildren(curve,legend);
  $("threshold-note").textContent = `Dashed line: fixed threshold ${model.threshold.toFixed(3)}, selected at the validation 80th percentile. Holdout fraction flagged: ${percent(model.flagged_fraction)}. A threshold targets approximate capacity; the ranked queue above enforces an exact slot cap. Precision is shown as 0 when no visits are flagged.`;
  const table = el("table", "");
  const head = el("tr", ""); ["Threshold", "Precision", "Recall", "Flagged"].forEach(t => head.append(el("th",t)));
  const thead = el("thead", ""); thead.append(head); table.append(thead);
  const body = el("tbody", "");
  data.validation_curve.forEach(r => { const row=el("tr",""); [r.threshold.toFixed(2),percent(r.precision),percent(r.recall),String(r.flagged)].forEach(v=>row.append(el("td",v)));body.append(row); });
  table.append(body); $("threshold-table").replaceChildren(table);
  const hist = chartFrame("Holdout appointment counts in ten predicted-risk bins");
  const max = Math.max(...data.holdout_risk_histogram.map(r=>r.count),1);
  for (const fraction of [0,.5,1]) hist.append(svgNode("line",{x1:45,x2:495,y1:y(fraction),y2:y(fraction),class:"gridline"}),svgNode("text",{x:35,y:y(fraction)+4,"text-anchor":"end"},String(Math.round(fraction*max))));
  data.holdout_risk_histogram.forEach((r,i) => {
    const bar=svgNode("rect",{x:48+i*45,y:y(r.count/max),width:35,height:180*r.count/max,fill:"#779ece"});
    bar.append(svgNode("title",{},`${r.from.toFixed(1)}–${r.to.toFixed(1)}: ${r.count} visits`));
    hist.append(bar,svgNode("text",{x:65+i*45,y:239,"text-anchor":"middle"},r.from.toFixed(1)),svgNode("text",{x:65+i*45,y:y(r.count/max)-7,"text-anchor":"middle"},String(r.count)));
  });
  hist.append(svgNode("text",{x:270,y:265,"text-anchor":"middle"},"Predicted risk · bin lower bound"));
  $("risk-chart").replaceChildren(hist);
  const features = model.coefficients.slice(0,10), maxCoef=Math.max(...features.map(r=>Math.abs(r.coefficient)),.01);
  const names = {lead_days:"Booking lead time",prior_no_shows:"Prior no-shows",reminder_sent:"Reminder sent",appointment_hour:"Appointment hour"};
  $("feature-chart").replaceChildren(...features.map(r=>{
    const field=r.feature.split("__")[1], label=names[field]||field.replaceAll("_"," ");
    const row=el("div","","feature-row"), track=el("div","","feature-track"), bar=el("div","","feature-bar"+(r.coefficient<0?" negative":""));
    const width=Math.abs(r.coefficient)/maxCoef*48;
    bar.style.width=width+"%";bar.style.left=(r.coefficient<0?50-width:50)+"%";track.append(bar);
    row.append(el("span",label),track,el("span",(r.coefficient>0?"+":"")+r.coefficient.toFixed(3)));return row;
  }));
}

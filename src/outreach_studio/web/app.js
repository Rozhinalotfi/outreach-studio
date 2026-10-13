// Outreach Studio web client. No build step: plain ES modules and the JSON API in server.py.

const $side = document.getElementById("side");
const $main = document.getElementById("main");
const TONES = ["warm", "professional", "direct", "casual", "formal"];
const LENGTHS = [["short", "Short"], ["medium", "Medium"], ["detailed", "Detailed"]];
const WORKING = new Set(["queued", "researching", "drafting", "judging"]);
const AGENT_COLORS = ["var(--accent)", "var(--ink)", "var(--gold)", "#4f8a8b", "#7a5cc7"];

// ── tiny DOM helper ──────────────────────────────────────────────────────────────
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
}
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, { headers: { "content-type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "HTTP " + r.status);
  return r.json();
}
const rel = ts => { if (!ts) return ""; const s = (Date.now() - ts) / 1000;
  return s < 60 ? "just now" : s < 3600 ? Math.floor(s / 60) + "m ago" : s < 86400 ? Math.floor(s / 3600) + "h ago" : new Date(ts).toLocaleDateString(); };
const host = u => { try { return new URL(u.startsWith("http") ? u : "https://" + u).hostname.replace("www.", ""); } catch { return u; } };

// ── state ─────────────────────────────────────────────────────────────────────────
let state = { runs: [], settings: {}, profile: {}, config: null };
let poll = null;
const colorOf = id => { const i = (state.config?.agents || []).findIndex(a => a.id === id); return AGENT_COLORS[(i < 0 ? 4 : i) % AGENT_COLORS.length]; };
const route = () => { const [, view, id] = (location.hash || "#/new").split("/"); return { view: view || "new", id }; };
const go = hash => { location.hash = hash; };
window.addEventListener("hashchange", render);

async function refreshShared() {
  [state.runs, state.settings, state.profile, state.config] = await Promise.all(
    [api("/runs"), api("/settings"), api("/profile"), api("/config")]);
}

// ── sidebar ───────────────────────────────────────────────────────────────────────
function statusLabel(r) {
  if (r.status === "needs_choice") return "Your call";
  if (r.status === "error") return "Needs retry";
  if (WORKING.has(r.status)) return { queued: "Starting", researching: "Researching", drafting: "Writing", judging: "Judging" }[r.status];
  return rel(r.createdAt);
}
function renderSide() {
  const { view, id } = route();
  $side.replaceChildren(
    h("div", { class: "row", style: { justifyContent: "space-between", marginBottom: "8px" } },
      h("div", { class: "brand" }, "Outreach Studio"), h("button", { class: "btn primary", onclick: () => go("#/new") }, "New")),
    h("div", { class: "list" },
      state.runs.length ? state.runs.map(r => h("button", { class: "item", "aria-current": String(view === "run" && id === r.id), onclick: () => go("#/run/" + r.id) },
        h("div", { class: "t" }, h("span", { class: "ellipsis" }, r.name || "Untitled"),
          h("span", { class: "small", style: { color: r.status === "needs_choice" ? "var(--accent)" : r.status === "error" ? "var(--err)" : "var(--faint)" } }, statusLabel(r))),
        h("div", { class: "small mute ellipsis" }, r.subject || r.purpose || "")))
        : h("div", { class: "small mute", style: { padding: "8px 11px" } }, "Your outreach will collect here.")),
    h("button", { class: "item small mute", "aria-current": String(view === "settings"), onclick: () => go("#/settings") }, "Settings: you, models & keys"));
}

// ── new outreach ──────────────────────────────────────────────────────────────────
function chips(options, value, onPick) {
  const wrap = h("div", { class: "row", style: { gap: "6px" } });
  const draw = v => wrap.replaceChildren(...options.map(([k, l]) => h("button", { class: "chip", type: "button", "aria-pressed": String(k === v), onclick: () => { onPick(k); draw(k); } }, l)));
  draw(value);
  return wrap;
}
const field = (label, hint, input) => h("div", { class: "field" }, h("div", {}, label, hint && h("span", { class: "faint small", style: { marginLeft: "8px" } }, hint)), input);

function renderNew() {
  const s = state.settings, cfg = state.config;
  const ready = (cfg?.agents || []).filter(a => a.ready).length;
  const f = { tone: s.defaultTone || "warm", length: "short" };
  const inp = (name, ph, tag = "input", rows = 3) => { const el = tag === "input" ? h("input", { type: "text", placeholder: ph }) : h("textarea", { rows, placeholder: ph }); f["$" + name] = el; return el; };
  const err = h("span", { class: "err small" });
  const submit = h("button", { class: "btn primary", style: { padding: "11px 22px" } }, "Brief the writers");
  submit.onclick = async () => {
    const body = { tone: f.tone, length: f.length };
    for (const k of ["name", "email", "links", "notes", "purpose", "outcome", "language"]) body[k] = f["$" + k].value;
    if (!body.name.trim() || !body.purpose.trim()) { err.textContent = "Name and purpose are required."; return; }
    submit.disabled = true; submit.textContent = "Starting…";
    try { const { id } = await api("/runs", { method: "POST", body }); await refreshShared(); go("#/run/" + id); }
    catch (e) { err.textContent = e.message; submit.disabled = false; submit.textContent = "Brief the writers"; }
  };
  const lang = inp("language", "English"); lang.value = "English"; lang.style.width = "150px";
  $main.replaceChildren(h("div", { class: "narrow" },
    h("h1", {}, "Who are we writing to?"),
    h("p", { class: "mute" }, "A researcher reads their profiles, independent writers on different models each draft the email, and they judge each other's drafts blind. If they can't agree, you choose."),
    ready < 2 && h("div", { class: "card", style: { borderColor: "var(--accent)" } }, "At least two agents need API keys. ", h("a", { href: "#/settings" }, "Add keys in Settings"), "."),
    !s.senderName && h("div", { class: "card", style: { marginTop: "12px" } }, "Tell the writers who you are first: ", h("a", { href: "#/settings" }, "your sender profile"), "."),
    s.senderName && h("div", { class: "small mute", style: { marginTop: "12px" } }, `From ${s.senderName}${s.senderRole ? ", " + s.senderRole : ""}`,
      state.profile.status === "done" && state.profile.enabled !== false ? " · GitHub profile on" : "", " · ", h("a", { href: "#/settings" }, "edit")),
    h("div", { class: "label", style: { marginTop: "24px" } }, "Recipient"),
    h("div", { class: "grid" }, field("Name", null, inp("name", "Dana Whitfield")), field("Email", "optional", inp("email", "dana@company.com"))),
    field("Profiles and links", "one per line", inp("links", "linkedin.com/in/…\nx.com/…\ntheir site, a talk, an article", "textarea")),
    field("Anything else you know", "paste freely", inp("notes", "Their LinkedIn About/experience (LinkedIn blocks automated reading, so pasting helps), how you know them…", "textarea", 4)),
    h("div", { class: "label", style: { marginTop: "24px" } }, "Purpose"),
    field("Why are you reaching out?", null, inp("purpose", "I'm setting up a design review process and want to learn how she runs critiques…", "textarea")),
    field("What should they do?", "optional", inp("outcome", "A 20-minute call in the next two weeks")),
    h("div", { class: "row", style: { gap: "0 28px", alignItems: "flex-start" } },
      field("Tone", null, chips(TONES.map(t => [t, t]), f.tone, v => f.tone = v)),
      field("Length", null, chips(LENGTHS, f.length, v => f.length = v)),
      field("Language", null, lang)),
    h("div", { class: "row", style: { marginTop: "24px" } }, submit, err)));
}

// ── a run ─────────────────────────────────────────────────────────────────────────
function stepBar(run) {
  const idx = { queued: 0, researching: 0, drafting: 1, judging: 2 }[run.status] ?? (run.status === "error" ? (run.judgments ? 2 : run.drafts ? 1 : 0) : 4);
  const steps = ["Research", "Draft", "Judge", "Decide"];
  return h("div", { class: "steps" }, steps.map((s, i) => [i > 0 && h("div", { class: "bar" + (i <= idx ? " on" : "") }),
    h("div", { class: "step" + (i <= idx ? " on" : "") + (i < idx ? " done" : "") + (i === idx && idx < 4 && run.status !== "error" ? " active" : "") }, h("span", { class: "pip" }), s)]));
}
function seats(run) {
  const agents = state.config?.agents?.filter(a => a.ready) || [];
  return h("div", { class: "grid", style: { marginTop: "14px", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" } }, agents.map(a => {
    const d = run.drafts?.[a.id] || {}, j = run.judgments?.[a.id] || {};
    const st = ["queued", "researching"].includes(run.status) ? "Waiting for the brief" : d.status === "writing" ? "Writing" : d.status === "failed" ? "Could not draft"
      : j.status === "judging" ? "Judging the others" : j.status === "done" ? "Judged" : d.status === "done" ? `Draft in · ${Math.round((d.ms || 0) / 1000)}s` : "Waiting";
    const live = st === "Writing" || st === "Judging the others";
    return h("div", { class: "card", style: { padding: "12px 14px" } },
      h("div", { class: "row", style: { gap: "8px" } }, h("span", { class: "dot", style: { background: colorOf(a.id) } }), a.persona),
      h("div", { class: "mono", style: { marginLeft: "17px" } }, `${a.provider}/${a.model}`),
      h("div", { class: "small " + (live ? "dots" : "mute"), style: { marginLeft: "17px", marginTop: "6px" } }, st));
  }));
}
function scoreboard(run) {
  const dec = run.decision; if (!dec?.table) return null;
  const J = Object.entries(run.judgments || {}).filter(([, v]) => v.status === "done");
  const pos = v => ((Math.max(1, Math.min(10, v)) - 1) / 9 * 100) + "%";
  return h("div", { class: "card", style: { marginTop: "16px" } },
    h("div", { class: "row", style: { justifyContent: "space-between" } }, h("div", { class: "label" }, "How the judges scored"),
      h("div", { class: "row small mute", style: { gap: "12px" } }, J.map(([jid, v]) => h("span", { class: "row", style: { gap: "5px" } }, h("span", { class: "dot", style: { background: colorOf(jid), width: "8px", height: "8px" } }), v.persona + " judge")),
        h("span", { class: "row", style: { gap: "5px" } }, h("span", { class: "dot", style: { border: "1.5px dashed var(--mute)", width: "8px", height: "8px" } }), "own draft, not counted"))),
    dec.order.map(did => {
      const d = run.drafts[did], row = dec.table[did], win = did === (run.chosen || dec.winner);
      return h("div", { class: "row", style: { padding: "8px 0", flexWrap: "nowrap" } },
        h("div", { style: { width: "120px", flex: "none", color: win ? "var(--ink)" : "var(--mute)" } }, d.persona),
        h("div", { class: "track" }, h("div", { class: "base" }),
          J.map(([jid, v], k) => { const sc = v.scores?.[did]; if (!sc) return null;
            return h("span", { class: "j" + (jid === did ? " self" : ""), title: `${v.persona} judge: ${sc.overall}${jid === did ? " (own draft, not counted)" : ""}\n${sc.note || ""}`,
              style: { left: pos(sc.overall), top: (7 + (k - 1) * 4) + "px", background: colorOf(jid) } }); }),
          h("div", { class: "mean", style: { left: pos(row.peer || 1) } })),
        h("div", { class: "score", style: { color: win ? "var(--accent)" : "var(--mute)" } }, (row.peer || 0).toFixed(1)));
    }),
    h("div", { class: "small faint", style: { textAlign: "center" } }, "peer average out of 10 · each dot is one judge"));
}
function draftCard(run, id, featured, onChoose) {
  const d = run.drafts?.[id]; if (!d) return null;
  if (d.status === "failed") return h("div", { class: "card" }, d.persona, h("div", { class: "small mute" }, "Could not draft: " + d.error));
  if (d.status !== "done") return null;
  const row = run.decision?.table?.[id], chosen = run.chosen === id;
  const body = h("div", { class: "body" + (featured ? "" : " clamp"), style: { marginTop: "10px" } }, d.body);
  const notes = Object.entries(run.judgments || {}).filter(([jid, v]) => v.status === "done" && jid !== id && v.scores?.[id]);
  const notesBox = h("div", { hidden: true }, notes.map(([jid, v]) => h("div", { class: "small mute", style: { marginTop: "6px" } },
    h("span", { style: { color: "var(--ink)" } }, `${v.persona}, ${v.scores[id].overall}/10: `), v.scores[id].note)));
  return h("div", { class: "card", style: { display: "flex", flexDirection: "column", borderColor: chosen ? "var(--accent)" : null } },
    h("div", { class: "row", style: { flexWrap: "nowrap", alignItems: "flex-start" } }, h("span", { class: "dot", style: { background: colorOf(id), marginTop: "7px" } }),
      h("div", { style: { flex: 1, minWidth: 0 } }, d.persona, h("div", { class: "mono" }, `${d.provider}/${d.model}`)),
      row && h("div", { class: "score", style: { color: chosen ? "var(--accent)" : "var(--mute)" } }, row.peer.toFixed(1))),
    h("div", { class: "small mute", style: { marginTop: "10px" } }, "Subject"), h("div", {}, d.subject), body,
    !featured && h("button", { class: "btn ghost", style: { alignSelf: "flex-start" }, onclick: e => { body.classList.remove("clamp"); e.target.remove(); } }, "Read all"),
    d.assumptions?.length ? h("div", { class: "small mute", style: { marginTop: "8px" } }, h("span", { style: { color: "var(--ink)" } }, "Verify before sending: "), d.assumptions.join("; ")) : null,
    notes.length ? h("button", { class: "btn ghost", style: { alignSelf: "flex-start" }, onclick: () => { notesBox.hidden = !notesBox.hidden; } }, "Judges' notes") : null, notesBox,
    h("div", { style: { flex: 1 } }),
    h("div", { style: { marginTop: "12px" } }, chosen ? h("span", { style: { color: "var(--accent)" } }, "Chosen")
      : h("button", { class: "btn" + (featured ? " primary" : ""), onclick: () => onChoose(id) }, "Use this one")));
}
function finalEditor(run, id, rerender) {
  const f = run.final, to = h("input", { type: "email", value: run.recipient?.email || "", placeholder: "their@email.com" });
  const subj = h("input", { type: "text", value: f.subject }), body = h("textarea", { rows: 12, value: f.body, style: { fontSize: "15px", lineHeight: "1.65" } });
  const msg = h("span", { class: "small mute" });
  const ask = h("input", { type: "text", placeholder: "Ask for a change: shorter, mention our mutual friend Sam, less formal…" });
  const enc = encodeURIComponent;
  const revise = h("button", { class: "btn" }, "Revise");
  revise.onclick = async () => {
    if (!ask.value.trim()) return; revise.disabled = true; revise.textContent = "Revising…";
    try { const r = await api(`/runs/${id}/revise`, { method: "POST", body: { text: ask.value } }); rerender(r); }
    catch (e) { msg.textContent = e.message; revise.disabled = false; revise.textContent = "Revise"; }
  };
  ask.addEventListener("keydown", e => { if (e.key === "Enter") revise.click(); });
  const versions = Object.entries(run.versions || {}).sort((a, b) => b[0] - a[0]);
  return h("div", { class: "card", style: { marginTop: "14px" } },
    h("div", { style: { display: "grid", gridTemplateColumns: "64px 1fr", gap: "10px", alignItems: "center" } }, h("span", { class: "label" }, "To"), to, h("span", { class: "label" }, "Subject"), subj),
    h("div", { style: { marginTop: "12px" } }, body),
    h("div", { class: "row", style: { marginTop: "12px" } },
      h("button", { class: "btn primary", onclick: () => window.open(`https://mail.google.com/mail/?view=cm&fs=1&to=${enc(to.value)}&su=${enc(subj.value)}&body=${enc(body.value)}`, "_blank", "noopener") }, "Open in Gmail"),
      h("button", { class: "btn", onclick: () => { location.href = `mailto:${enc(to.value)}?subject=${enc(subj.value)}&body=${enc(body.value)}`; } }, "Mail app"),
      h("button", { class: "btn", onclick: async () => { try { await navigator.clipboard.writeText(`Subject: ${subj.value}\n\n${body.value}`); msg.textContent = "Copied"; } catch { msg.textContent = "Copy failed"; } } }, "Copy"),
      h("button", { class: "btn", onclick: async () => { rerender(await api(`/runs/${id}/final`, { method: "PUT", body: { subject: subj.value, body: body.value } })); } }, "Save edits"), msg),
    h("div", { class: "row", style: { marginTop: "12px", flexWrap: "nowrap" } }, ask, revise),
    versions.length ? h("details", { style: { marginTop: "10px" } }, h("summary", { class: "small mute" }, `Earlier versions (${versions.length})`),
      versions.map(([, v]) => h("div", { class: "row small", style: { borderTop: "1px solid var(--line)", padding: "6px 0" } },
        h("span", { class: "mute" }, `v${v.version || 1}`), h("span", { class: "ellipsis", style: { flex: 1 } }, v.subject),
        h("button", { class: "btn ghost", onclick: async () => rerender(await api(`/runs/${id}/final`, { method: "PUT", body: { subject: v.subject, body: v.body } })) }, "Restore")))) : null,
    h("div", { class: "small faint", style: { marginTop: "10px" } }, "Nothing is sent from here. Review, then send from your mail app."));
}
function brief(b) {
  if (!b) return null;
  const list = (t, a) => a?.length ? [h("div", { class: "label", style: { marginTop: "12px" } }, t), h("ul", {}, a.map(x => h("li", {}, typeof x === "string" ? x : JSON.stringify(x))))] : null;
  return h("details", { class: "card", style: { marginTop: "16px" } },
    h("summary", {}, h("span", { class: "label" }, "Research brief"), " ", h("span", { class: "small mute" }, `${b.confidence || ""} confidence · ${b.pagesRead ?? 0} pages read`)),
    h("p", {}, b.summary), list("Background", b.background), list("Recent", b.recent),
    b.hooks?.length ? [h("div", { class: "label", style: { marginTop: "12px" } }, "Hooks"), b.hooks.map(x => h("div", { style: { marginTop: "6px" } }, x.fact,
      h("div", { class: "small mute" }, x.relevance, " · ", String(x.source || "").startsWith("http") ? h("a", { href: x.source, target: "_blank", rel: "noreferrer" }, host(x.source)) : x.source)))] : null,
    list("Careful with", b.cautions),
    b.sources?.length ? h("div", { class: "row small", style: { marginTop: "12px" } }, b.sources.map(s => h("a", { href: s.url, target: "_blank", rel: "noreferrer" }, s.title || host(s.url)))) : null);
}
async function renderRun(id) {
  let run;
  try { run = await api("/runs/" + id); } catch { $main.replaceChildren(h("div", { class: "mute" }, "This outreach no longer exists.")); return; }
  const draw = r => {
    run = r;
    const dec = r.decision, rec = r.recipient || {};
    const onChoose = async did => { draw(await api(`/runs/${id}/choose/${did}`, { method: "POST" })); refreshShared().then(renderSide); };
    const working = WORKING.has(r.status);
    const header = h("div", { class: "row", style: { alignItems: "flex-start" } },
      h("div", { style: { flex: 1, minWidth: "220px" } },
        h("div", { class: "label" }, `${statusLabel(r)} · ${rel(r.createdAt)}`), h("h1", {}, rec.name || "Untitled"), h("div", { class: "mute" }, r.purpose),
        h("div", { class: "row small", style: { marginTop: "6px" } }, (rec.links || "").split(/\s+/).filter(Boolean).map(l => h("a", { href: l.startsWith("http") ? l : "https://" + l, target: "_blank", rel: "noreferrer" }, host(l))))),
      h("button", { class: "btn ghost", onclick: async () => { if (confirmDel()) { await api("/runs/" + id, { method: "DELETE" }); await refreshShared(); go("#/new"); } } }, "Delete"));
    let decision = null;
    if (dec && (dec.mode === "consensus" || r.chosen)) {
      decision = h("div", { style: { marginTop: "20px" } }, h("h2", { style: { color: "var(--accent)", margin: 0 } },
        r.chosenBy === "you" ? `You chose ${r.drafts[r.chosen].persona}` : `The panel agreed on ${r.drafts[dec.winner].persona}`),
        h("div", { class: "mute" }, r.chosenBy === "you" ? "Saved to your preferences so future writers and judges learn your taste." : dec.reason));
    } else if (dec) {
      decision = h("div", { style: { marginTop: "20px" } }, h("h2", { style: { color: "var(--accent)", margin: 0 } }, "Your call"), h("div", {}, dec.reason),
        dec.tradeoff && h("div", { class: "callout", style: { marginTop: "10px" } }, dec.tradeoff),
        h("div", { class: "grid", style: { marginTop: "14px" } }, dec.contenders.map(c => draftCard(r, c, true, onChoose))));
    }
    $main.replaceChildren(h("div", { class: "wrap" }, header, stepBar(r),
      r.status === "error" && h("div", { class: "card row", style: { marginTop: "12px", borderColor: "var(--err)" } }, h("div", { style: { flex: 1 } }, r.error),
        h("button", { class: "btn primary", onclick: async () => { await api(`/runs/${id}/retry`, { method: "POST" }); renderRun(id); } }, "Retry")),
      working && ["queued", "researching"].includes(r.status) && h("div", { class: "dots", style: { marginTop: "12px" } }, `Reading ${rec.name ? rec.name.split(" ")[0] + "'s" : "their"} profiles and recent work`),
      (working || !dec) && r.status !== "error" && seats(r),
      decision, r.final && finalEditor(r, id, draw), scoreboard(r), brief(r.brief),
      Object.keys(r.drafts || {}).length ? [h("div", { class: "label", style: { marginTop: "24px" } }, dec ? "All drafts" : "Drafts so far"),
        h("div", { class: "grid", style: { marginTop: "10px" } }, (dec?.order || Object.keys(r.drafts)).map(did => draftCard(r, did, false, onChoose)))] : null));
    clearInterval(poll);
    if (working) poll = setInterval(async () => { if (route().id !== id) return clearInterval(poll); const n = await api("/runs/" + id);
      if (n.updatedAt !== run.updatedAt) { draw(n); refreshShared().then(renderSide); } }, 1500);
  };
  draw(run);
}
function confirmDel() { return window.confirm("Delete this outreach?"); }

// ── settings ──────────────────────────────────────────────────────────────────────
function renderSettings() {
  const s = state.settings, cfg = state.config, p = state.profile || {};
  const el = {};
  const t = (k, ph, rows) => (el[k] = rows ? h("textarea", { rows, placeholder: ph, value: s[k] || "" }) : h("input", { type: "text", placeholder: ph, value: s[k] || "" }));
  let tone = s.defaultTone || "warm";
  const saved = h("span", { class: "small mute" });
  const save = async () => { const body = { defaultTone: tone }; for (const k in el) body[k] = el[k].value; state.settings = await api("/settings", { method: "PATCH", body }); saved.textContent = "Saved"; renderSide(); };

  const keyRow = (name, ready) => {
    const v = h("input", { type: "password", placeholder: ready ? "configured · paste to replace" : "paste key", autocomplete: "off" });
    const st = h("span", { class: "small " + (ready ? "" : "faint") }, ready ? "✓ set" : "not set");
    return h("div", { class: "row", style: { marginTop: "8px", flexWrap: "nowrap" } }, h("span", { class: "mono", style: { width: "190px", flex: "none" } }, name), v,
      h("button", { class: "btn", onclick: async () => { if (!v.value) return; state.config = await api("/keys", { method: "POST", body: { name, value: v.value } }); v.value = ""; renderSettings(); } }, "Save"),
      ready && h("button", { class: "btn ghost", onclick: async () => { state.config = await api("/keys", { method: "POST", body: { name, value: null } }); renderSettings(); } }, "Remove"), st);
  };
  const keyNames = [...new Set(Object.values(cfg.providers).map(x => x.api_key_env).filter(Boolean))];
  const searchKey = { exa: "EXA_API_KEY", tavily: "TAVILY_API_KEY", brave: "BRAVE_API_KEY" };

  const agentsBox = h("textarea", { rows: 10, class: "mono", style: { fontSize: "12.5px" }, value: JSON.stringify({ agents: cfg.agents.map(({ ready, ...a }) => a), roles: cfg.roles, search: { provider: cfg.search.provider } }, null, 2) });
  const agentsMsg = h("span", { class: "small" });

  const login = h("input", { type: "text", placeholder: "your GitHub username", value: s.githubLogin || p.login || "" });
  const analyzing = p.status === "analyzing";
  const groups = ["demonstrated", "working", "exposure"];

  $main.replaceChildren(h("div", { class: "narrow" },
    h("h1", {}, "Settings"),
    h("div", { class: "label", style: { marginTop: "24px" } }, "You, the sender"),
    h("div", { class: "grid" }, field("Your name", null, t("senderName", "Your name")), field("Role", "optional", t("senderRole", "Founder at …"))),
    field("About you", "what makes you credible", t("senderBackground", "What you do and have built", 3)),
    field("Sign-off", null, t("signature", "Best,\nYour name", 2)),
    field("Default tone", null, chips(TONES.map(x => [x, x]), tone, v => tone = v)),
    field("Style notes", "always / never", t("styleNotes", "Never use exclamation marks. Keep it under 120 words.", 2)),
    h("div", { class: "row", style: { marginTop: "12px" } }, h("button", { class: "btn primary", onclick: save }, "Save"), saved),

    h("div", { class: "label", style: { marginTop: "34px" } }, "Your technical background, from GitHub"),
    h("p", { class: "small mute" }, "One model writes a developer profile from your public repositories (languages, dependencies, source samples, commit history); a second model on another provider audits every claim against that evidence. Writers then describe you only through it. Add a GITHUB_TOKEN below for higher rate limits."),
    h("div", { class: "row", style: { flexWrap: "nowrap" } }, login, h("button", { class: "btn", disabled: analyzing, onclick: async () => { await api("/profile/analyze", { method: "POST", body: { text: login.value } }); state.profile = { status: "analyzing" }; renderSettings(); waitProfile(); } }, analyzing ? "Analyzing…" : p.status === "done" ? "Re-analyze" : "Analyze")),
    p.status === "error" && h("div", { class: "err small", style: { marginTop: "8px" } }, p.error),
    p.status === "done" && h("div", { class: "card", style: { marginTop: "12px" } },
      h("div", { class: "row" }, h("strong", { style: { color: "var(--accent)", textTransform: "capitalize" } }, p.level?.label || ""),
        h("span", { class: "small mute" }, `${p.repoCount} repos · ${p.analyst} → audited by ${p.auditor}`),
        h("label", { class: "row small", style: { marginLeft: "auto", gap: "6px" } }, h("input", { type: "checkbox", checked: p.enabled !== false, onchange: async e => { state.profile = await api("/profile", { method: "PATCH", body: { enabled: e.target.checked } }); } }), "Use in emails")),
      h("p", {}, p.summary),
      groups.map(g => { const sk = (p.skills || []).filter(x => x.level === g); return sk.length ? [h("div", { class: "label", style: { marginTop: "8px" } }, g),
        h("div", { class: "row", style: { gap: "6px", marginTop: "6px" } }, sk.map(x => h("span", { class: "pill", title: (x.note || "") + "\nEvidence: " + (x.evidence || []).join(", ") }, x.name)))] : null; }),
      p.claimable?.length ? [h("div", { class: "label", style: { marginTop: "12px" } }, "What the writers may say"), h("ul", {}, p.claimable.map(c => h("li", {}, c)))] : null,
      p.avoid?.length ? [h("div", { class: "label" }, "What they won't claim"), h("ul", { class: "mute small" }, p.avoid.map(c => h("li", {}, c)))] : null),

    h("div", { class: "label", style: { marginTop: "34px" } }, "API keys"),
    h("p", { class: "small mute" }, "Stored only on this machine (", h("span", { class: "mono" }, "~/.outreach-studio/keys.json"), ", owner-readable) or read from your environment / .env. Values are never shown again or sent to the browser."),
    keyNames.map(n => keyRow(n, Object.values(cfg.providers).some(x => x.api_key_env === n && x.ready))),
    keyRow("GITHUB_TOKEN", cfg.github_token),
    cfg.search.provider !== "none" && searchKey[cfg.search.provider] && keyRow(searchKey[cfg.search.provider], cfg.search.ready),

    h("div", { class: "label", style: { marginTop: "34px" } }, "The panel"),
    cfg.agents.map(a => h("div", { class: "row small", style: { marginTop: "8px" } }, h("span", { class: "dot", style: { background: colorOf(a.id) } }), a.persona,
      h("span", { class: "mono" }, `${a.provider}/${a.model}`), h("span", { class: a.ready ? "" : "err" }, a.ready ? "ready" : "needs key"))),
    h("details", { style: { marginTop: "12px" } }, h("summary", { class: "small" }, "Edit agents, roles and search (JSON)"),
      h("p", { class: "small mute" }, "Any number of agents (two or more). Providers: anthropic, openai, gemini, openrouter, ollama, or add your own OpenAI-compatible provider in agents.yaml. Search: exa | tavily | brave | none."),
      agentsBox, h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "btn", onclick: async () => {
        try { state.config = await api("/config", { method: "PUT", body: JSON.parse(agentsBox.value) }); agentsMsg.textContent = "Saved"; renderSettings(); }
        catch (e) { agentsMsg.textContent = e.message; agentsMsg.className = "small err"; } } }, "Save panel"), agentsMsg))));
}
function waitProfile() {
  const t = setInterval(async () => { state.profile = await api("/profile"); if (state.profile.status !== "analyzing") { clearInterval(t); if (route().view === "settings") renderSettings(); } }, 3000);
}

// ── router ────────────────────────────────────────────────────────────────────────
async function render() {
  clearInterval(poll);
  await refreshShared();
  renderSide();
  const { view, id } = route();
  if (view === "run" && id) return renderRun(id);
  if (view === "settings") return renderSettings();
  return renderNew();
}
render();

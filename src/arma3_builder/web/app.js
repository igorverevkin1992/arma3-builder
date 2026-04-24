// arma3-builder — single-page UI.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let lastPlan = null;
let currentMissionIdx = 0;
let lastPayload = null;          // last generate/stream done payload

// ------------------------------ Wizard state ------------------------------

const wizard = {
    step: 0,
    data: {
        scope: null,             // "single" | "campaign"
        templateId: null,
        map: "Tanoa",
        side: "WEST",
        enemySide: "EAST",
        playerCount: 4,
        timeOfDay: "06:30",
        weather: "overcast",
        title: "Untitled",
    },
};

function renderWizardStep() {
    const panel = $("#wizard-panel");
    const steps = $$("#wizard-steps li");
    steps.forEach((li, i) => {
        li.classList.remove("active", "done");
        if (i === wizard.step) li.classList.add("active");
        if (i < wizard.step) li.classList.add("done");
    });

    const stepRenderers = [stepScope, stepTheatre, stepTeam, stepReview];
    panel.innerHTML = "";
    stepRenderers[wizard.step](panel);
    $("#wizard-back").disabled = wizard.step === 0;
    $("#wizard-next").textContent = wizard.step === 3 ? "Generate" : "Next →";
}

function stepScope(panel) {
    panel.innerHTML = `
        <label>What are you building?</label>
        <div class="option ${wizard.data.scope === "single" ? "selected" : ""}" data-scope="single">
            <div class="title">Single mission</div>
            <div class="desc">One standalone mission from a template.</div>
        </div>
        <div class="option ${wizard.data.scope === "campaign" ? "selected" : ""}" data-scope="campaign">
            <div class="title">Campaign</div>
            <div class="desc">Multiple missions with a shared arc.</div>
        </div>
        <label>Pick a starting template:</label>
        <select id="wiz-template"></select>
    `;
    // Inject templates from the cache populated at boot.
    const sel = $("#wiz-template");
    (wizard.templates || []).forEach((t) => {
        const o = document.createElement("option");
        o.value = t.id;
        o.textContent = `${t.label} — ${t.summary}`;
        sel.appendChild(o);
    });
    if (wizard.data.templateId) sel.value = wizard.data.templateId;
    sel.addEventListener("change", () => { wizard.data.templateId = sel.value; });
    $$("#wizard-panel .option").forEach((el) => {
        el.addEventListener("click", () => {
            wizard.data.scope = el.dataset.scope;
            renderWizardStep();
        });
    });
}

function stepTheatre(panel) {
    panel.innerHTML = `
        <label>Map</label>
        <select id="wiz-map">
          ${["Tanoa", "Altis", "Stratis", "Malden", "Enoch", "VR"].map(
            (m) => `<option ${m === wizard.data.map ? "selected" : ""}>${m}</option>`
          ).join("")}
        </select>
        <label>Time of day</label>
        <input id="wiz-tod" value="${wizard.data.timeOfDay}">
        <label>Weather</label>
        <select id="wiz-weather">
          ${["clear", "overcast", "rain", "storm"].map(
            (w) => `<option ${w === wizard.data.weather ? "selected" : ""}>${w}</option>`
          ).join("")}
        </select>
    `;
    $("#wiz-map").addEventListener("change", (e) => wizard.data.map = e.target.value);
    $("#wiz-tod").addEventListener("change", (e) => wizard.data.timeOfDay = e.target.value);
    $("#wiz-weather").addEventListener("change", (e) => wizard.data.weather = e.target.value);
}

function stepTeam(panel) {
    panel.innerHTML = `
        <label>Mission title</label>
        <input id="wiz-title" value="${wizard.data.title}">
        <label>Player slots (coop)</label>
        <input id="wiz-count" type="number" min="1" max="16" value="${wizard.data.playerCount}">
        <label>Player side</label>
        <select id="wiz-side">
          ${["WEST", "EAST", "INDEPENDENT"].map(
            (s) => `<option ${s === wizard.data.side ? "selected" : ""}>${s}</option>`
          ).join("")}
        </select>
        <label>Enemy side</label>
        <select id="wiz-enemy">
          ${["WEST", "EAST", "INDEPENDENT", "CIVILIAN"].map(
            (s) => `<option ${s === wizard.data.enemySide ? "selected" : ""}>${s}</option>`
          ).join("")}
        </select>
    `;
    $("#wiz-title").addEventListener("input", (e) => wizard.data.title = e.target.value);
    $("#wiz-count").addEventListener("change", (e) => wizard.data.playerCount = +e.target.value);
    $("#wiz-side").addEventListener("change", (e) => wizard.data.side = e.target.value);
    $("#wiz-enemy").addEventListener("change", (e) => wizard.data.enemySide = e.target.value);
}

function stepReview(panel) {
    const d = wizard.data;
    panel.innerHTML = `
        <div class="option">
            <div class="title">${escapeHtml(d.title)} — ${escapeHtml(d.templateId || "?")}</div>
            <div class="desc">
                ${escapeHtml(d.map)} · ${escapeHtml(d.side)} vs ${escapeHtml(d.enemySide)}
                · ${d.playerCount} players · ${escapeHtml(d.timeOfDay)} · ${escapeHtml(d.weather)}
            </div>
        </div>
        <p class="muted small">Click <b>Generate</b> below to build the mission.
           You can follow it up in the Refine panel afterwards.</p>
    `;
}

$("#wizard-back").addEventListener("click", () => {
    if (wizard.step > 0) { wizard.step--; renderWizardStep(); }
});
$("#wizard-next").addEventListener("click", async () => {
    if (wizard.step < 3) {
        wizard.step++;
        renderWizardStep();
    } else {
        await generateFromWizard();
    }
});

async function generateFromWizard() {
    if (!wizard.data.templateId) {
        alert("Please pick a template in step 1");
        return;
    }
    // Instantiate the template with wizard params, then wrap into a brief.
    const params = {
        title: wizard.data.title,
        map: wizard.data.map,
        side: wizard.data.side,
        enemy_side: wizard.data.enemySide,
        player_count: wizard.data.playerCount,
        time_of_day: wizard.data.timeOfDay,
        weather: wizard.data.weather,
    };
    const tplResp = await fetch(`/templates/${wizard.data.templateId}/instantiate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Id": getSessionId() },
        body: JSON.stringify(params),
    });
    const tpl = await tplResp.json();
    const body = {
        brief: {
            name: wizard.data.title,
            author: "designer",
            overview: tpl.blueprint.brief.summary,
            mods: ["cba_main"],
            factions: { WEST: "BLU_F", EAST: "OPF_F" },
            missions: [tpl.blueprint.brief],
        },
    };
    clearProgress();
    await streamGeneration(body);
}

// Stable session id so concurrent browser tabs / users get isolated
// per-session diff state on the backend (see _session_runs in routes.py).
function getSessionId() {
    try {
        let sid = localStorage.getItem("a3b_session");
        if (!sid) {
            sid = "s_" + Math.random().toString(36).slice(2, 12);
            localStorage.setItem("a3b_session", sid);
        }
        return sid;
    } catch (e) {
        return "anon";
    }
}

// -------- Tab switching -------------------------------------------------
$$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
        $$(".tab").forEach((t) => t.classList.remove("active"));
        $$(".tab-body").forEach((b) => b.classList.add("hidden"));
        tab.classList.add("active");
        document.querySelector(`.tab-body[data-tab="${tab.dataset.tab}"]`).classList.remove("hidden");
    });
});

// -------- Templates -----------------------------------------------------
function renderTemplateParams() {
    const sel = $("#template-id");
    if (!sel.options[sel.selectedIndex]) return;
    const t = JSON.parse(sel.options[sel.selectedIndex].dataset.tmpl);
    const container = $("#template-params");
    container.innerHTML = "";
    t.parameters.forEach((p) => {
        const wrap = document.createElement("div");
        wrap.style.margin = "6px 0";
        const label = document.createElement("label");
        label.textContent = p.label;
        label.style.fontSize = "11px";
        label.style.color = "#8b949e";
        label.style.display = "block";
        const inp = document.createElement("input");
        inp.name = p.name;
        inp.value = p.default ?? "";
        inp.dataset.kind = p.kind;
        wrap.appendChild(label);
        wrap.appendChild(inp);
        container.appendChild(wrap);
    });
}

function collectTemplateParams() {
    const out = {};
    $$("#template-params input").forEach((inp) => {
        let v = inp.value;
        if (inp.dataset.kind === "int") v = parseInt(v, 10);
        if (inp.dataset.kind === "float") v = parseFloat(v);
        out[inp.name] = v;
    });
    return out;
}

// -------- Progress rendering --------------------------------------------
function addProgress(text, klass = "running") {
    const li = document.createElement("li");
    li.textContent = text;
    li.className = klass;
    $("#progress").appendChild(li);
    return li;
}

function clearProgress() {
    $("#progress").innerHTML = "";
    $("#result").classList.add("hidden");
    $("#diff-panel").classList.add("hidden");
}

// -------- Generate via SSE ----------------------------------------------
async function generate() {
    clearProgress();
    const activeTab = document.querySelector(".tab.active").dataset.tab;
    const body = {};
    if (activeTab === "wizard") {
        // Wizard has its own button; Generate button is still allowed for
        // power users who wizard-then-Generate without hitting Next.
        return generateFromWizard();
    }
    if (activeTab === "prompt") {
        body.prompt = $("#prompt").value.trim();
        if (!body.prompt) return alert("Please type a prompt");
    } else if (activeTab === "template") {
        const id = $("#template-id").value;
        const params = collectTemplateParams();
        const tplResp = await fetch(`/templates/${id}/instantiate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        });
        const tpl = await tplResp.json();
        body.brief = {
            name: params.title || tpl.blueprint.brief.title,
            author: "designer",
            overview: tpl.blueprint.brief.summary,
            mods: ["cba_main"],
            factions: { WEST: "BLU_F", EAST: "OPF_F" },
            missions: [tpl.blueprint.brief],
        };
    } else {
        try {
            body.brief = JSON.parse($("#brief").value);
        } catch (e) {
            return alert("Invalid brief JSON: " + e.message);
        }
    }
    await streamGeneration(body);
}

async function streamGeneration(body) {
    const li = addProgress("Streaming…", "running");
    const resp = await fetch("/generate/stream", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Session-Id": getSessionId(),
        },
        body: JSON.stringify(body),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
            const chunk = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            handleSseChunk(chunk);
        }
    }
    li.classList.remove("running");
    li.classList.add("done");
}

function handleSseChunk(chunk) {
    const lines = chunk.split("\n");
    let event = "message";
    let data = "";
    lines.forEach((l) => {
        if (l.startsWith("event:")) event = l.slice(6).trim();
        if (l.startsWith("data:")) data = l.slice(5).trim();
    });
    if (!data) return;
    const payload = JSON.parse(data);
    if (event === "agent_started") {
        addProgress(`▶ ${payload.agent}`, "running");
    } else if (event === "agent_done") {
        const li = addProgress(`✓ ${payload.agent}  ${JSON.stringify(payload).slice(0, 80)}`, "done");
    } else if (event === "qa_iteration") {
        addProgress(`QA iteration ${payload.iteration} (${payload.errors}E / ${payload.warnings}W)`, "running");
    } else if (event === "error") {
        addProgress("✗ " + payload.message, "error");
    } else if (event === "done") {
        renderResult(payload);
    }
}

// -------- Result rendering ----------------------------------------------
function renderResult(payload) {
    addProgress(`🎉 output: ${payload.output_path}`, "done");
    $("#result").classList.remove("hidden");
    lastPlan = payload.plan;
    lastPayload = payload;

    // Score grid
    const s = payload.score || {};
    $("#score").innerHTML = Object.entries(s).map(([k, v]) => `
        <div class="metric"><div class="val">${v}</div><div class="label">${k}</div></div>
    `).join("");

    renderUsage(payload.usage);
    renderPacing(payload.pacing);
    renderPlaytest(payload.playtest);

    // Missions
    $("#missions").innerHTML = (payload.plan.blueprints || []).map((bp, i) => `
        <div class="mission ${i === 0 ? "selected" : ""}" data-idx="${i}">
            <h4>${bp.brief.title}</h4>
            <div class="meta">${bp.brief.map} · ${bp.brief.side} vs ${bp.brief.enemy_side}
                 · ${bp.units.length} units · ${bp.fsm.states.length} FSM states</div>
        </div>
    `).join("");
    $$("#missions .mission").forEach((el) => {
        el.addEventListener("click", () => {
            $$("#missions .mission").forEach((m) => m.classList.remove("selected"));
            el.classList.add("selected");
            currentMissionIdx = parseInt(el.dataset.idx, 10);
            drawFsm(lastPlan.blueprints[currentMissionIdx]);
            drawMap(lastPlan.blueprints[currentMissionIdx]);
        });
    });
    drawFsm(lastPlan.blueprints[0]);
    drawMap(lastPlan.blueprints[0]);

    // Launch
    const l = payload.launch || {};
    $("#launch").innerHTML = `
        <div class="label">Arma 3 editor command (click to copy):</div>
        <div class="cmd" onclick="copyText(this)">${escapeHtml(l.editor_cmd || "")}</div>
        <div class="label">Steam URI:</div>
        <div class="cmd" onclick="copyText(this)">${escapeHtml(l.steam_uri || "")}</div>
        <div class="label muted small">${escapeHtml((l.copy_paths && l.copy_paths.campaign_hint) || "")}</div>
    `;

    // QA findings placeholder (SSE done event does not carry the full QA,
    // fetch it via a secondary endpoint if you want richer details — for now
    // we just render the error/warning counts.
    $("#qa-summary").textContent =
        ` · ${payload.errors || 0} errors, ${payload.warnings || 0} warnings`;
}

// -------- Usage / cost / pacing / playtest ------------------------------

function renderUsage(usage) {
    const el = $("#usage");
    if (!usage || !el) return;
    const cells = [
        ["$" + (usage.total_cost_usd || 0).toFixed(4), "cost"],
        [usage.calls || 0, "LLM calls"],
        [(usage.total_input_tokens || 0) + " / " + (usage.total_output_tokens || 0), "in / out tokens"],
        [(usage.total_latency_ms || 0) + " ms", "latency"],
    ];
    el.innerHTML = cells.map(([v, k]) =>
        `<div class="cell"><div class="v">${escapeHtml(String(v))}</div><div class="k">${k}</div></div>`
    ).join("");
    $("#usage-summary").textContent = usage.calls
        ? ` · ${usage.calls} calls across ${Object.keys(usage.by_role || {}).length} agents`
        : "";
}

function renderPacing(pacing) {
    const el = $("#pacing");
    if (!el) return;
    el.innerHTML = "";
    if (!pacing || !pacing.missions) return;
    for (const m of pacing.missions) {
        const total = m.total_seconds || 0;
        const row = document.createElement("div");
        row.className = "pacing-row";
        const mins = Math.round(total / 60);
        const eng = Math.round((m.engagement_ratio || 0) * 100);
        row.innerHTML = `
            <div class="pacing-label">
                <span>${escapeHtml(m.mission_id || "mission")}</span>
                <span>~${mins} min · ${eng}% combat</span>
            </div>
            <div class="pacing-bar">
                ${(m.timeline || []).map((seg) => {
                    const pct = total > 0 ? (seg.seconds / total * 100).toFixed(2) : 0;
                    return `<div class="pacing-seg" style="width:${pct}%"
                                 data-kind="${escapeHtml(seg.kind)}">
                        <span class="tip">${escapeHtml(seg.label)} · ${seg.seconds}s · ${escapeHtml(seg.kind)}</span>
                    </div>`;
                }).join("")}
            </div>
        `;
        el.appendChild(row);
    }
}

function renderPlaytest(playtest) {
    const el = $("#playtest");
    if (!el) return;
    el.innerHTML = "";
    if (!playtest || !playtest.length) {
        el.innerHTML = `<li class="muted">No simulated-playthrough findings.</li>`;
        return;
    }
    const findings = [];
    for (const report of playtest) {
        for (const f of (report.findings || [])) {
            findings.push(f);
        }
    }
    if (!findings.length) {
        el.innerHTML = `<li>✓ All FSMs are reachable and terminal-convergent.</li>`;
        return;
    }
    el.innerHTML = findings.map((f) => `
        <li class="${escapeHtml(f.severity)}">
            <code>${escapeHtml(f.code)}</code>
            ${escapeHtml(f.message)}
            ${f.suggestion ? `<div class="muted small">→ ${escapeHtml(f.suggestion)}</div>` : ""}
        </li>
    `).join("");
}

// -------- FSM canvas drawing --------------------------------------------
function drawFsm(bp) {
    if (!bp) return;
    $("#fsm-mission-label").textContent = "Mission: " + bp.brief.title;
    const c = $("#fsm");
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    const nodes = bp.fsm.states;
    const initial = bp.fsm.initial;

    // Simple vertical layout.
    const marginX = 60, startY = 40, dy = Math.max(70, (c.height - 80) / nodes.length);
    const positions = {};
    nodes.forEach((n, i) => {
        positions[n.id] = { x: c.width / 2, y: startY + i * dy };
    });

    // Edges
    ctx.strokeStyle = "#58a6ff";
    ctx.lineWidth = 1.5;
    nodes.forEach((n) => {
        (n.transitions || []).forEach((t) => {
            const from = positions[n.id], to = positions[t.to];
            if (!from || !to) return;
            ctx.beginPath();
            ctx.moveTo(from.x, from.y + 18);
            // curve slightly so parallel edges don't overlap
            const cpx = from.x + (t.to === n.id ? 120 : 0);
            const cpy = (from.y + to.y) / 2;
            ctx.quadraticCurveTo(cpx, cpy, to.x, to.y - 18);
            ctx.stroke();
            // arrowhead
            const ang = Math.atan2(to.y - 18 - cpy, to.x - cpx);
            ctx.beginPath();
            ctx.moveTo(to.x, to.y - 18);
            ctx.lineTo(to.x - 6 * Math.cos(ang - 0.4), to.y - 18 - 6 * Math.sin(ang - 0.4));
            ctx.lineTo(to.x - 6 * Math.cos(ang + 0.4), to.y - 18 - 6 * Math.sin(ang + 0.4));
            ctx.closePath();
            ctx.fillStyle = "#58a6ff";
            ctx.fill();
        });
    });

    // Nodes
    nodes.forEach((n) => {
        const p = positions[n.id];
        ctx.beginPath();
        ctx.roundRect ? ctx.roundRect(p.x - 90, p.y - 18, 180, 36, 6) : ctx.rect(p.x - 90, p.y - 18, 180, 36);
        ctx.fillStyle = n.terminal ? (n.endType === "loser" ? "#6e1a1a" : "#1e4620") :
                        (n.id === initial ? "#1f3d63" : "#21262d");
        ctx.fill();
        ctx.strokeStyle = "#30363d";
        ctx.stroke();
        ctx.fillStyle = "#f0f6fc";
        ctx.font = "12px ui-monospace, monospace";
        ctx.textAlign = "center";
        ctx.fillText(n.label || n.id, p.x, p.y + 4);
        if (n.terminal) {
            ctx.fillStyle = "#8b949e";
            ctx.font = "10px ui-monospace, monospace";
            ctx.fillText(`end: ${n.endType || "?"}`, p.x, p.y + 16);
        }
    });
}

// -------- Map preview (top-down, view-only) -----------------------------
//
// Renders units, waypoints and markers in world coordinates fitted into
// the canvas. Hover over any feature for a tooltip with its metadata.
let mapHoverIndex = null;
function drawMap(bp) {
    const c = $("#map");
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    if (!bp) return;

    // Collect points.
    const pts = [];
    for (const u of (bp.units || [])) {
        pts.push({
            x: u.position[0], y: u.position[1],
            kind: u.is_player ? "player" : "enemy",
            side: u.side,
            label: (u.name || u.classname) + " · " + u.side,
        });
    }
    for (const w of (bp.waypoints || [])) {
        pts.push({
            x: w.position[0], y: w.position[1],
            kind: "waypoint", side: "",
            label: "waypoint " + (w.type || ""),
        });
    }
    if (!pts.length) return;

    // Bounds with 10% padding.
    const minX = Math.min(...pts.map((p) => p.x));
    const maxX = Math.max(...pts.map((p) => p.x));
    const minY = Math.min(...pts.map((p) => p.y));
    const maxY = Math.max(...pts.map((p) => p.y));
    const pad = 40;
    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    const W = c.width - 2 * pad;
    const H = c.height - 2 * pad;
    const scale = Math.min(W / spanX, H / spanY);
    const offX = pad + (W - spanX * scale) / 2;
    const offY = pad + (H - spanY * scale) / 2;

    // Invert Y so north is up.
    const screen = (p) => ({
        x: offX + (p.x - minX) * scale,
        y: c.height - (offY + (p.y - minY) * scale),
    });

    // Grid.
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth = 0.5;
    for (let i = 0; i < 5; i++) {
        const y = (c.height / 5) * i;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(c.width, y); ctx.stroke();
        const x = (c.width / 5) * i;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, c.height); ctx.stroke();
    }

    // Title + axes hint.
    ctx.fillStyle = "#8b949e";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillText(`${bp.brief.map}  ·  ${pts.length} features`, 8, 14);

    // Features.
    const screenPts = pts.map((p) => ({ ...p, ...screen(p) }));
    screenPts.forEach((p, i) => {
        ctx.beginPath();
        let color = "#6e7681";
        let r = 3;
        if (p.kind === "player")    { color = "#58a6ff"; r = 5; }
        else if (p.kind === "enemy"){ color = (p.side === "EAST" ? "#f85149" : "#d29922"); r = 4; }
        else if (p.kind === "waypoint") { color = "#7ee787"; r = 3; }
        ctx.fillStyle = color;
        ctx.arc(p.x, p.y, r + (i === mapHoverIndex ? 2 : 0), 0, Math.PI * 2);
        ctx.fill();
    });

    // Hover handling.
    c.onmousemove = (e) => {
        const rect = c.getBoundingClientRect();
        const mx = (e.clientX - rect.left) * (c.width / rect.width);
        const my = (e.clientY - rect.top) * (c.height / rect.height);
        let best = null, bestDist = 12;
        screenPts.forEach((p, i) => {
            const d = Math.hypot(p.x - mx, p.y - my);
            if (d < bestDist) { best = i; bestDist = d; }
        });
        if (best !== mapHoverIndex) {
            mapHoverIndex = best;
            $("#map-hover").textContent = best === null
                ? ""
                : `${screenPts[best].label}  @  ${screenPts[best].x.toFixed(0)}, ${screenPts[best].y.toFixed(0)}`;
            drawMap(bp);
        }
    };
    c.onmouseleave = () => { mapHoverIndex = null; $("#map-hover").textContent = ""; drawMap(bp); };
}

// -------- Refine --------------------------------------------------------
$("#refine").addEventListener("click", async () => {
    const instr = $("#refine-input").value.trim();
    if (!instr || !lastPlan) return;
    addProgress(`refine: ${instr}`, "running");
    const r = await fetch("/refine", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Session-Id": getSessionId(),
        },
        body: JSON.stringify({ plan: lastPlan, instruction: instr }),
    });
    if (!r.ok) {
        const txt = await r.text();
        addProgress("✗ refine failed: " + txt.slice(0, 120), "error");
        return;
    }
    const payload = await r.json();
    lastPlan = payload.plan;
    renderResult({
        ...payload,
        errors: (payload.qa.findings || []).filter((f) => f.severity === "error").length,
        warnings: (payload.qa.findings || []).filter((f) => f.severity === "warning").length,
    });
    // Render diff
    if (payload.diff && payload.diff.length) {
        $("#diff-panel").classList.remove("hidden");
        const list = $("#diff-list");
        list.innerHTML = "";
        payload.diff
            .filter((d) => d.change !== "unchanged")
            .forEach((d) => {
                const wrap = document.createElement("div");
                wrap.className = "diff-item";
                const head = document.createElement("div");
                head.className = "diff-header";
                head.innerHTML = `<span class="badge ${d.change}">${d.change}</span>${escapeHtml(d.path)}`;
                const body = document.createElement("div");
                body.className = "diff-body";
                body.innerHTML = (d.unified || "(no diff)")
                    .split("\n")
                    .map((line) => {
                        const cls = line.startsWith("+") ? "add"
                                  : line.startsWith("-") ? "del" : "";
                        return `<span class="${cls}">${escapeHtml(line)}</span>`;
                    }).join("\n");
                head.addEventListener("click", () => {
                    body.style.display = body.style.display === "block" ? "none" : "block";
                });
                wrap.appendChild(head);
                wrap.appendChild(body);
                list.appendChild(wrap);
            });
    }
});

// -------- Preview -------------------------------------------------------
$("#preview").addEventListener("click", async () => {
    clearProgress();
    addProgress("previewing…", "running");
    const body = {};
    const tab = document.querySelector(".tab.active").dataset.tab;
    if (tab === "prompt") body.prompt = $("#prompt").value.trim();
    else if (tab === "brief") body.brief = JSON.parse($("#brief").value);
    else return alert("Use Prompt or Brief tab for preview");
    const r = await fetch("/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await r.json();
    lastPlan = data.plan;
    drawFsm(data.plan.blueprints[0]);
    addProgress(`✓ preview: ${data.plan.blueprints.length} missions`, "done");
});

// -------- Utilities -----------------------------------------------------
function escapeHtml(s) {
    return (s || "").replace(/[&<>"]/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[c]));
}
window.copyText = function (el) {
    navigator.clipboard.writeText(el.textContent);
    const prev = el.style.background;
    el.style.background = "#1e4620";
    setTimeout(() => (el.style.background = prev), 400);
};

$("#generate").addEventListener("click", generate);

// Boot: fetch templates once; populate the wizard *and* the classic
// "Template" tab dropdown; render the wizard's first step.
(async function boot() {
    const r = await fetch("/templates");
    const templates = await r.json();
    wizard.templates = templates;
    wizard.data.templateId = templates[0] ? templates[0].id : null;
    populateTemplateTab(templates);
    renderWizardStep();
})();

function populateTemplateTab(templates) {
    const sel = $("#template-id");
    if (!sel) return;
    sel.innerHTML = "";
    templates.forEach((t) => {
        const o = document.createElement("option");
        o.value = t.id;
        o.textContent = `${t.label} — ${t.summary}`;
        o.dataset.tmpl = JSON.stringify(t);
        sel.appendChild(o);
    });
    sel.addEventListener("change", renderTemplateParams);
    renderTemplateParams();
}

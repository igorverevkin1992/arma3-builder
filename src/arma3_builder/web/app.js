// arma3-builder — single-page UI.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let lastPlan = null;
let currentMissionIdx = 0;

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
async function loadTemplates() {
    const r = await fetch("/templates");
    const templates = await r.json();
    const sel = $("#template-id");
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
        // Wrap blueprint into a minimal one-mission brief and submit.
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

    // Score grid
    const s = payload.score || {};
    $("#score").innerHTML = Object.entries(s).map(([k, v]) => `
        <div class="metric"><div class="val">${v}</div><div class="label">${k}</div></div>
    `).join("");

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
        });
    });
    drawFsm(lastPlan.blueprints[0]);

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
loadTemplates();

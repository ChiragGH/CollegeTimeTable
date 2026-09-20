/**
 * College Timetable System — Single-Page Application
 *
 * All 10 pages rendered client-side.  All data fetched from the
 * Flask JSON API at /api/*.  Zero scheduling logic in the frontend.
 */

// ================================================================
// API Client
// ================================================================

const api = {
    async get(url) {
        const r = await fetch(url);
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
    },
    async post(url, data) {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(err.error || `${r.status} ${r.statusText}`);
        }
        return r.json();
    },
    async del(url) {
        const r = await fetch(url, { method: 'DELETE' });
        return r.json();
    },
};

// ================================================================
// State
// ================================================================

const state = {
    currentSession: localStorage.getItem('currentSession') || null,
    currentTimetable: localStorage.getItem('currentTimetable') || null,
    highlightSlot: null,
    set session(id) {
        this.currentSession = id;
        if (id) localStorage.setItem('currentSession', id);
        else localStorage.removeItem('currentSession');
    },
    get session() { return this.currentSession; },
    set timetable(id) {
        this.currentTimetable = id;
        if (id) localStorage.setItem('currentTimetable', id);
        else localStorage.removeItem('currentTimetable');
    },
    get timetable() { return this.currentTimetable; },
};

// ================================================================
// Router
// ================================================================

const routes = {
    dashboard:   renderDashboard,
    timetables:  renderTimetablesWorkspace,
    master:      renderMaster,
    setup:       renderSetup,
    sections:    renderSections,
    assignments: renderAssignments,
    rooms:       renderRooms,
    generate:    renderGenerate,
    report:      renderReport,
    viewer:      renderViewer,
    export:      renderExport,
};

function navigate(page) {
    const fn = routes[page] || routes.dashboard;
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
    });
    fn();
}

window.addEventListener('hashchange', () => {
    const page = location.hash.slice(1) || 'dashboard';
    navigate(page);
});

document.addEventListener('DOMContentLoaded', () => {
    const page = location.hash.slice(1) || 'dashboard';
    navigate(page);
});

// ================================================================
// Helpers
// ================================================================

const $ = id => document.getElementById(id);
const content = () => $('page-content');

// Global HTML escaper for safely rendering backend-provided text.
const htmlEsc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function toast(msg, type = 'info') {
    const c = $('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

function html(strings, ...vals) {
    return strings.reduce((s, str, i) => s + str + (vals[i] ?? ''), '');
}

function sessionGuard() {
    if (!state.session) {
        content().innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                <h3>No Active Session</h3>
                <p>Create a new timetable session first.</p>
                <a href="#setup" class="btn btn-primary mt-16">Create New Timetable</a>
            </div>`;
        return false;
    }
    return true;
}

// ================================================================
// Timetable Management Workspace
// ================================================================

async function renderTimetablesWorkspace() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const stats = await api.get('/api/dashboard/stats');
        const branches = stats.branches || ['CSE', 'ECE', 'EE', 'ME', 'Civil'];

        const curYear = window._wsFilterYear || '2026-27';
        const curBranch = window._wsFilterBranch || '';
        const curSem = window._wsFilterSem || '';
        const curSec = window._wsFilterSec || '';
        const curStatus = window._wsFilterStatus || '';

        let query = `?academic_year=${encodeURIComponent(curYear)}`;
        if (curBranch) query += `&branch=${encodeURIComponent(curBranch)}`;
        if (curSem) query += `&semester=${encodeURIComponent(curSem)}`;
        if (curSec) query += `&section=${encodeURIComponent(curSec)}`;
        if (curStatus) query += `&status=${encodeURIComponent(curStatus)}`;

        const timetables = await api.get(`/api/timetables${query}`);

        content().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
            <div>
                <h1>Timetables Workspace</h1>
                <p>Manage, inspect, edit, validate, and export independent college timetables</p>
            </div>
            <div class="flex gap-8">
                <a href="#setup" class="btn btn-primary">+ New Timetable</a>
                <button class="btn btn-secondary" onclick="renderTimetablesWorkspace()">↻ Refresh</button>
            </div>
        </div>

        <div class="workspace-toolbar">
            <div class="workspace-filters">
                <div>
                    <label style="font-size:11px;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px">Academic Year</label>
                    <select id="ws-filter-year" onchange="applyWsFilters()">
                        <option value="2026-27" ${curYear==='2026-27'?'selected':''}>2026-27</option>
                        <option value="2025-26" ${curYear==='2025-26'?'selected':''}>2025-26</option>
                    </select>
                </div>
                <div>
                    <label style="font-size:11px;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px">Branch</label>
                    <select id="ws-filter-branch" onchange="applyWsFilters()">
                        <option value="">All Branches</option>
                        ${branches.map(b => `<option value="${b}" ${curBranch===b?'selected':''}>${b}</option>`).join('')}
                    </select>
                </div>
                <div>
                    <label style="font-size:11px;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px">Semester</label>
                    <select id="ws-filter-sem" onchange="applyWsFilters()">
                        <option value="">All Semesters</option>
                        <option value="1" ${curSem==='1'?'selected':''}>Semester 1</option>
                        <option value="2" ${curSem==='2'?'selected':''}>Semester 2</option>
                        <option value="3" ${curSem==='3'?'selected':''}>Semester 3</option>
                        <option value="4" ${curSem==='4'?'selected':''}>Semester 4</option>
                        <option value="5" ${curSem==='5'?'selected':''}>Semester 5</option>
                        <option value="6" ${curSem==='6'?'selected':''}>Semester 6</option>
                    </select>
                </div>
                <div>
                    <label style="font-size:11px;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px">Section</label>
                    <select id="ws-filter-sec" onchange="applyWsFilters()">
                        <option value="">All Sections</option>
                        <option value="A" ${curSec==='A'?'selected':''}>Section A</option>
                        <option value="B" ${curSec==='B'?'selected':''}>Section B</option>
                        <option value="C" ${curSec==='C'?'selected':''}>Section C</option>
                    </select>
                </div>
                <div>
                    <label style="font-size:11px;font-weight:600;color:var(--text-secondary);display:block;margin-bottom:4px">Status</label>
                    <select id="ws-filter-status" onchange="applyWsFilters()">
                        <option value="">All Statuses</option>
                        <option value="VALID" ${curStatus==='VALID'?'selected':''}>Valid</option>
                        <option value="CONFLICTING" ${curStatus==='CONFLICTING'?'selected':''}>Conflicting</option>
                        <option value="INCOMPLETE" ${curStatus==='INCOMPLETE'?'selected':''}>Incomplete</option>
                        <option value="DRAFT" ${curStatus==='DRAFT'?'selected':''}>Draft</option>
                    </select>
                </div>
            </div>
            <div style="font-size:13px;font-weight:600;color:var(--text-secondary)">
                ${timetables.length} Timetable${timetables.length===1?'':'s'}
            </div>
        </div>

        ${timetables.length === 0 ? `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <h3>No Timetables Found</h3>
                <p>No generated timetables match the selected filters. Create and generate a new timetable setup.</p>
                <a href="#setup" class="btn btn-primary mt-16">Generate New Timetable</a>
            </div>
        ` : `
            <div class="timetables-grid">
                ${timetables.map(tt => {
                    const statusBadge = tt.status === 'VALID' ? 'badge-green' :
                        tt.status === 'CONFLICTING' ? 'badge-conflicting' :
                        tt.status === 'INCOMPLETE' ? 'badge-incomplete' : 'badge-draft';
                    const statusText = tt.status === 'VALID' ? '✓ Valid' :
                        tt.status === 'CONFLICTING' ? '⚠ Conflicting' :
                        tt.status === 'INCOMPLETE' ? 'Partial' : 'Draft';
                    return `
                    <div class="tt-card ${tt.status === 'VALID' ? 'is-valid' : tt.status === 'CONFLICTING' ? 'has-conflict' : ''}" id="card-${tt.timetable_id}">
                        <div class="tt-card-header">
                            <div>
                                <div class="tt-card-title">${htmlEsc(tt.display_name)}</div>
                                <div class="tt-card-sub">${htmlEsc(tt.academic_year)} · <code>${htmlEsc(tt.context_code)}</code></div>
                            </div>
                            <span class="badge ${statusBadge}">${statusText}</span>
                        </div>
                        <div class="tt-card-meta">
                            <span>📦 <strong>${tt.placements_count}</strong> classes</span>
                            <span>🏷 Version <strong>v${tt.version}</strong></span>
                            <span>🕒 ${tt.updated_at ? tt.updated_at.replace('T', ' ') : '—'}</span>
                        </div>
                        <div class="tt-card-actions">
                            <button class="btn btn-primary btn-sm" onclick="openTimetable('${tt.timetable_id}')">Open Grid</button>
                            <button class="btn btn-secondary btn-sm" onclick="validateTimetableAction('${tt.timetable_id}')">Validate</button>
                            <button class="btn btn-secondary btn-sm" onclick="exportTimetableAction('${tt.timetable_id}')">Export</button>
                            <button class="btn btn-secondary btn-sm" onclick="regenerateTimetableAction('${tt.timetable_id}')" title="Regenerate placements">Regen</button>
                            <button class="btn btn-secondary btn-sm" onclick="duplicateTimetableAction('${tt.timetable_id}')" title="Clone timetable">Clone</button>
                            <button class="btn btn-sm" style="color:var(--error);margin-left:auto" onclick="deleteTimetableAction('${tt.timetable_id}')" title="Delete timetable">✕</button>
                        </div>
                    </div>`;
                }).join('')}
            </div>
        `}
        `;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error loading workspace</h3><p>${e.message}</p></div>`;
    }
}

function applyWsFilters() {
    window._wsFilterYear = $('ws-filter-year')?.value || '2026-27';
    window._wsFilterBranch = $('ws-filter-branch')?.value || '';
    window._wsFilterSem = $('ws-filter-sem')?.value || '';
    window._wsFilterSec = $('ws-filter-sec')?.value || '';
    window._wsFilterStatus = $('ws-filter-status')?.value || '';
    renderTimetablesWorkspace();
}

function openTimetable(id) {
    state.timetable = id;
    location.hash = 'viewer';
}

function exportTimetableAction(id) {
    state.timetable = id;
    location.hash = 'export';
}

async function validateTimetableAction(id) {
    try {
        const res = await api.get(`/api/timetable/${id}/validate`);
        if (res.is_valid) {
            toast(`✓ Timetable "${res.display_name}" is VALID with zero clashes.`, 'success');
        } else {
            toast(`⚠ ${res.total_conflicts} conflict(s) detected in "${res.display_name}"!`, 'error');
            state.timetable = id;
            location.hash = 'report';
        }
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function regenerateTimetableAction(id) {
    const confirmMsg = "Regeneration will replace the current placements and may remove manual edits. Do you want to proceed?";
    if (!confirm(confirmMsg)) return;
    try {
        toast('Regenerating timetable…', 'info');
        const res = await api.post(`/api/timetable/${id}/regenerate`, {});
        toast(`Timetable "${id}" regenerated!`, 'success');
        renderTimetablesWorkspace();
    } catch (e) {
        toast(`Regeneration failed: ${e.message}`, 'error');
    }
}

async function duplicateTimetableAction(id) {
    try {
        const res = await api.post(`/api/timetable/${id}/duplicate`, {});
        toast(`Duplicated as "${res.timetable.timetable_id}"!`, 'success');
        renderTimetablesWorkspace();
    } catch (e) {
        toast(`Duplicate failed: ${e.message}`, 'error');
    }
}

async function deleteTimetableAction(id) {
    if (!confirm(`Are you sure you want to delete timetable "${id}"? This will not affect other timetables.`)) return;
    try {
        await api.del(`/api/timetable/${id}`);
        toast(`Timetable "${id}" deleted.`, 'success');
        if (state.timetable === id) state.timetable = null;
        renderTimetablesWorkspace();
    } catch (e) {
        toast(`Delete failed: ${e.message}`, 'error');
    }
}

// ================================================================
// Page 1: Dashboard
// ================================================================

async function renderDashboard() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const stats = await api.get('/api/dashboard/stats');
        const sessions = await api.get('/api/session/list');
        content().innerHTML = `
        <div class="page-header">
            <h1>Dashboard</h1>
            <p>Welcome to the College Timetable Management System</p>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon blue">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                </div>
                <div>
                    <div class="stat-value">${stats.teachers.active}</div>
                    <div class="stat-label">Active Teachers</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon teal">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                </div>
                <div>
                    <div class="stat-value">${stats.rooms.active}</div>
                    <div class="stat-label">Active Rooms</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
                </div>
                <div>
                    <div class="stat-value">${stats.subjects.total}</div>
                    <div class="stat-label">Subjects</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon amber">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                </div>
                <div>
                    <div class="stat-value">${sessions.length}</div>
                    <div class="stat-label">Timetable Sessions</div>
                </div>
            </div>
        </div>
        <div class="flex gap-16" style="flex-wrap:wrap">
            <div class="card" style="flex:1; min-width: 300px">
                <div class="card-header"><h2>Branches</h2></div>
                <div class="card-body">
                    <div class="flex flex-wrap gap-8">
                        ${stats.branches.map(b => `<span class="badge badge-blue">${b}</span>`).join('')}
                    </div>
                </div>
            </div>
            <div class="card" style="flex:1; min-width: 300px">
                <div class="card-header">
                    <h2>Recent Sessions</h2>
                    <a href="#setup" class="btn btn-primary btn-sm">+ New</a>
                </div>
                <div class="card-body">
                    ${sessions.length === 0 ? '<p class="text-muted text-sm">No sessions yet</p>' :
                    sessions.slice(-5).reverse().map(s => `
                        <div class="flex items-center justify-between" style="padding:8px 0; border-bottom:1px solid var(--border)">
                            <div>
                                <strong>${s.session_id}</strong>
                                <span class="text-muted text-sm"> — ${s.branch} Sem ${s.semester}</span>
                            </div>
                            <div class="flex gap-8">
                                ${s.has_result ? '<span class="badge badge-green">Generated</span>' : '<span class="badge badge-gray">Draft</span>'}
                                <button class="btn btn-secondary btn-sm" onclick="loadSession('${s.session_id}')">Open</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error loading dashboard</h3><p>${e.message}</p></div>`;
    }
}

function loadSession(id) {
    state.session = id;
    toast(`Session "${id}" loaded`, 'success');
    navigate('assignments');
}

// ================================================================
// Page 2: Master Data
// ================================================================

async function renderMaster() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const [teachers, rooms, subjects, workloads, validation] = await Promise.all([
            api.get('/api/master/teachers'),
            api.get('/api/master/rooms'),
            api.get('/api/master/subjects'),
            api.get('/api/master/workloads'),
            api.get('/api/master/validate'),
        ]);

        content().innerHTML = `
        <div class="page-header">
            <h1>Master Data</h1>
            <p>Teachers, rooms, subjects, and workloads from Excel files</p>
        </div>
        <div class="flex items-center gap-16 mb-24">
            <span class="badge ${validation.valid ? 'badge-green' : 'badge-red'}">
                ${validation.valid ? '✓ All Valid' : `✗ ${validation.errors.length} Error(s)`}
            </span>
            ${validation.warnings.length > 0 ? `<span class="badge badge-amber">${validation.warnings.length} Warning(s)</span>` : ''}
        </div>

        <div class="tabs" id="master-tabs">
            <button class="tab active" onclick="showMasterTab('teachers')">Teachers (${teachers.length})</button>
            <button class="tab" onclick="showMasterTab('rooms')">Rooms (${rooms.length})</button>
            <button class="tab" onclick="showMasterTab('subjects')">Subjects (${subjects.length})</button>
            <button class="tab" onclick="showMasterTab('workloads')">Workloads (${workloads.length})</button>
            <button class="tab" onclick="showMasterTab('validation')">Validation</button>
        </div>

        <div id="master-tab-teachers" class="card">
            <div class="card-body">
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>ID</th><th>Name</th><th>Department</th><th>Designation</th><th>Status</th></tr></thead>
                        <tbody>${teachers.map(t => `
                            <tr>
                                <td><code>${t.teacher_id}</code></td>
                                <td>${t.teacher_name}</td>
                                <td><span class="badge badge-blue">${t.department}</span></td>
                                <td>${t.designation || '—'}</td>
                                <td>${t.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-gray">Inactive</span>'}</td>
                            </tr>
                        `).join('')}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="master-tab-rooms" class="card hidden">
            <div class="card-body">
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Branch</th><th>Shared</th><th>Status</th></tr></thead>
                        <tbody>${rooms.map(r => `
                            <tr>
                                <td><code>${r.room_id}</code></td>
                                <td>${r.room_name}</td>
                                <td><span class="badge badge-${r.room_type === 'LAB' ? 'green' : r.room_type === 'LECTURE' ? 'blue' : 'amber'}">${r.room_type}</span></td>
                                <td>${r.branch || '—'}</td>
                                <td>${r.is_shared ? 'Yes' : 'No'}</td>
                                <td>${r.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-gray">Inactive</span>'}</td>
                            </tr>
                        `).join('')}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="master-tab-subjects" class="card hidden">
            <div class="card-body">
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>ID</th><th>Code</th><th>Short Name</th><th>Name</th><th>Branch</th><th>Semester</th></tr></thead>
                        <tbody>${subjects.map(s => `
                            <tr>
                                <td><code>${s.subject_id}</code></td>
                                <td>${s.subject_code}</td>
                                <td><strong style="color:var(--primary, #2563eb)">${s.short_name || '—'}</strong></td>
                                <td>${s.subject_name}</td>
                                <td><span class="badge badge-blue">${s.branch}</span></td>
                                <td>${s.semester}</td>
                            </tr>
                        `).join('')}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="master-tab-workloads" class="card hidden">
            <div class="card-body">
                <div class="table-wrapper">
                    <table>
                        <thead><tr><th>ID</th><th>Subject ID</th><th>Branch</th><th>Sem</th><th>Lecture/wk</th><th>Practical/wk</th><th>Total/wk</th></tr></thead>
                        <tbody>${workloads.map(w => `
                            <tr>
                                <td><code>${w.workload_id}</code></td>
                                <td>${w.subject_id}</td>
                                <td><span class="badge badge-blue">${w.branch}</span></td>
                                <td>${w.semester}</td>
                                <td>${w.lecture_periods_per_week}</td>
                                <td>${w.practical_periods_per_week}</td>
                                <td><strong>${w.total_periods_per_week}</strong></td>
                            </tr>
                        `).join('')}</tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="master-tab-validation" class="card hidden">
            <div class="card-body">
                ${validation.errors.length === 0 && validation.warnings.length === 0
                    ? '<p class="text-muted text-sm">No validation issues found ✓</p>'
                    : ''}
                ${validation.errors.map(e => `
                    <div class="validation-item"><span class="badge badge-red">ERROR</span><div><strong>${e.code}</strong> — ${e.message} ${e.entity ? `(${e.entity})` : ''}</div></div>
                `).join('')}
                ${validation.warnings.map(w => `
                    <div class="validation-item"><span class="badge badge-amber">WARN</span><div><strong>${w.code}</strong> — ${w.message} ${w.entity ? `(${w.entity})` : ''}</div></div>
                `).join('')}
            </div>
        </div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

function showMasterTab(tab) {
    document.querySelectorAll('[id^="master-tab-"]').forEach(el => el.classList.add('hidden'));
    const el = document.getElementById(`master-tab-${tab}`);
    if (el) el.classList.remove('hidden');
    document.querySelectorAll('#master-tabs .tab').forEach((t, i) => {
        const tabs = ['teachers', 'rooms', 'subjects', 'workloads', 'validation'];
        t.classList.toggle('active', tabs[i] === tab);
    });
}

// ================================================================
// Page 3: Create New Timetable
// ================================================================

async function renderSetup() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const branches = await api.get('/api/filters/branches');

        content().innerHTML = `
        <div class="page-header">
            <h1>Create New Timetable</h1>
            <p>Set up academic year, branch, and semester</p>
        </div>
        <div class="card" style="max-width:640px">
            <div class="card-body">
                <div class="form-group">
                    <label>Session ID</label>
                    <input type="text" id="setup-session-id" placeholder="e.g. CSE-SEM3-2026" />
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Academic Year</label>
                        <input type="text" id="setup-year" value="2026-27" />
                    </div>
                    <div class="form-group">
                        <label>Branch</label>
                        <select id="setup-branch" onchange="onBranchChange()">
                            <option value="">Select branch…</option>
                            ${branches.map(b => `<option value="${b}">${b}</option>`).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>Semester</label>
                    <select id="setup-semester" disabled>
                        <option value="">Select branch first…</option>
                    </select>
                </div>
            </div>
            <div class="card-footer text-right">
                <button class="btn btn-primary btn-lg" onclick="createSession()">Create Timetable Session</button>
            </div>
        </div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

async function onBranchChange() {
    const branch = $('setup-branch').value;
    const semSel = $('setup-semester');
    if (!branch) { semSel.disabled = true; return; }
    const semesters = await api.get(`/api/filters/semesters?branch=${branch}`);
    semSel.innerHTML = '<option value="">Select semester…</option>' +
        semesters.map(s => `<option value="${s}">${s}</option>`).join('');
    semSel.disabled = false;
    // Auto-suggest session ID
    $('setup-session-id').value = `${branch}-SEM${semesters[0] || ''}-${$('setup-year').value}`;
}

async function createSession() {
    const sid = $('setup-session-id').value.trim();
    const branch = $('setup-branch').value;
    const sem = $('setup-semester').value;
    const year = $('setup-year').value;

    if (!sid || !branch || !sem) { toast('Fill in all fields', 'error'); return; }

    try {
        await api.post('/api/session/create', {
            session_id: sid, branch, semester: parseInt(sem), academic_year: year,
        });
        state.session = sid;
        toast(`Session "${sid}" created`, 'success');
        navigate('sections');
    } catch (e) {
        toast(e.message, 'error');
    }
}

// ================================================================
// Page 4: Class / Section Setup
// ================================================================

async function renderSections() {
    if (!sessionGuard()) return;
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const sess = await api.get(`/api/session/${state.session}`);
        const sections = sess.sections || [];

        content().innerHTML = `
        <div class="page-header">
            <h1>Sections &amp; Groups</h1>
            <p>Session: <strong>${state.session}</strong> — ${sess.branch} Semester ${sess.semester}</p>
        </div>
        <div class="card" style="max-width:640px">
            <div class="card-header">
                <h2>Configure Sections</h2>
            </div>
            <div class="card-body">
                <p class="text-sm text-muted mb-16">Add sections (e.g. A, B, C). Each section will have groups G1 and G2 for practicals.</p>
                <div id="section-list">
                    ${sections.map((s, i) => `<div class="flex items-center gap-8 mb-16">
                        <input type="text" class="section-input" value="${s}" style="max-width:200px" />
                        <button class="btn btn-danger btn-sm" onclick="this.parentElement.remove()">✕</button>
                    </div>`).join('')}
                </div>
                <button class="btn btn-secondary btn-sm" onclick="addSectionInput()">+ Add Section</button>
            </div>
            <div class="card-footer text-right">
                <button class="btn btn-primary" onclick="saveSections()">Save Sections</button>
                <a href="#assignments" class="btn btn-success" style="margin-left:8px">Next →</a>
            </div>
        </div>`;

        // If no sections yet, add one default
        if (sections.length === 0) addSectionInput();
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

function addSectionInput() {
    const list = $('section-list');
    const count = list.querySelectorAll('.section-input').length;
    const letter = String.fromCharCode(65 + count);
    const div = document.createElement('div');
    div.className = 'flex items-center gap-8 mb-16';
    div.innerHTML = `
        <input type="text" class="section-input" value="${letter}" style="max-width:200px" />
        <button class="btn btn-danger btn-sm" onclick="this.parentElement.remove()">✕</button>`;
    list.appendChild(div);
}

async function saveSections() {
    const inputs = document.querySelectorAll('.section-input');
    const sections = Array.from(inputs).map(el => el.value.trim()).filter(Boolean);
    if (sections.length === 0) { toast('Add at least one section', 'error'); return; }
    try {
        await api.post(`/api/session/${state.session}/sections`, { sections });
        toast('Sections saved', 'success');
    } catch (e) {
        toast(e.message, 'error');
    }
}

// ================================================================
// Page 5: Teacher-Subject Assignment
// ================================================================

// Per-visit state for the assignment page (reset on every render).
// Weekly periods are NEVER stored here as an editable value — they are
// always derived from the master workload via the workload-summary API.
let asgn = {
    session: null,
    summary: [],
    catalog: {},       // subject_id → workload status entry
    teachers: [],
    defaultBlocks: { LECTURE: 1, PRACTICAL: 2, WORKSHOP: 3, DRAWING: 3 },
};

function asgnSectionLabels() {
    const s = asgn.session && asgn.session.sections;
    return (s && s.length) ? s : ['A'];
}

async function renderAssignments() {
    if (!sessionGuard()) return;
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const sess = await api.get(`/api/session/${state.session}`);
        const subjects = await api.get(`/api/filters/subjects?branch=${sess.branch}&semester=${sess.semester}`);
        const teachers = await api.get(`/api/filters/teachers?branch=${encodeURIComponent(sess.branch)}`);

        asgn = {
            session: sess,
            summary: [],
            catalog: {},
            teachers,
            defaultBlocks: { LECTURE: 1, PRACTICAL: 2, WORKSHOP: 3, DRAWING: 3 },
        };

        content().innerHTML = `
        <div class="page-header">
            <h1>Teaching Assignments</h1>
            <p>Session: <strong>${state.session}</strong> — ${sess.branch} Semester ${sess.semester}</p>
        </div>
        <div class="flex gap-16" style="flex-wrap:wrap">
            <div class="card" style="flex:1;min-width:380px">
                <div class="card-header"><h2>Add Assignment</h2></div>
                <div class="card-body">
                    <div class="form-row">
                        <div class="form-group">
                            <label>Section</label>
                            <select id="asgn-section" onchange="onSectionChange()">
                                ${asgnSectionLabels().map(s => `<option value="${s}">${s}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Group</label>
                            <select id="asgn-group" onchange="onGroupChange()">
                                <option value="ALL">ALL (Lecture)</option>
                                <option value="G1">G1</option>
                                <option value="G2">G2</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Subject</label>
                        <select id="asgn-subject" onchange="onSubjectChange()">
                            <option value="">Select subject…</option>
                            ${subjects.map(s => `<option value="${s.subject_id}">${s.subject_code} — ${s.subject_name}${s.short_name ? ` [${s.short_name}]` : ''}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Teacher <span class="text-muted text-sm">(eligible for ${sess.branch} only)</span></label>
                        <select id="asgn-teacher" onchange="asgnUpdateWorkloadDisplay()">
                            <option value="">Select teacher…</option>
                            ${(teachers || []).map(t => `<option value="${t.teacher_id}">${t.teacher_name} (${t.department})</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Activity Type</label>
                            <select id="asgn-activity" onchange="onActivityChange()">
                                <option value="LECTURE">Lecture</option>
                                <option value="PRACTICAL">Practical</option>
                                <option value="WORKSHOP">Workshop</option>
                                <option value="DRAWING">Drawing</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Weekly Periods <span class="text-muted text-sm">(from workload)</span></label>
                            <input type="number" id="asgn-periods" value="" readOnly
                                   title="Derived from the master workload — not editable" />
                        </div>
                    </div>
                    <div id="asgn-preview" class="text-sm text-muted" style="margin-bottom:12px"></div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Block Size (slots/session)</label>
                            <input type="number" id="asgn-block" value="1" min="1" max="4" onchange="asgnUpdateWorkloadDisplay()" />
                        </div>
                        <div class="form-group">
                            <label>Sessions per Week <span class="text-muted text-sm">(= periods ÷ block)</span></label>
                            <input type="number" id="asgn-sessions" value="" readOnly title="Derived: weekly periods ÷ block size" />
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Preferred Room (optional)</label>
                        <select id="asgn-room"><option value="">No preference</option></select>
                    </div>
                    <div id="asgn-remaining" class="text-sm" style="margin-bottom:8px"></div>
                    <div id="asgn-msg" class="text-sm" style="min-height:20px"></div>
                </div>
                <div class="card-footer text-right">
                    <button class="btn btn-secondary" onclick="autoFillAssignment()">Auto Fill Next</button>
                    <button id="asgn-auto-btn" class="btn btn-success" onclick="autoAddAssignment()"
                            title="Development/testing utility: creates full subject test package (Lecture + G1/G2 Practicals) from master data">
                        Auto Add Test Assignment <span class="badge badge-amber">DEV</span>
                    </button>
                    <button id="asgn-add-btn" class="btn btn-primary" onclick="addAssignment()" disabled>Add Assignment</button>
                </div>
            </div>
            <div class="card" style="flex:1.5;min-width:400px">
                <div class="card-header">
                    <h2>Current Assignments (${sess.assignments.length})</h2>
                    <a href="#generate" class="btn btn-success btn-sm">Generate →</a>
                </div>
                <div class="card-body">
                    ${sess.assignments.length === 0
                    ? '<p class="text-muted text-sm">No assignments yet. Add one from the form, or use Auto Add Test Assignment.</p>'
                    : `<div class="table-wrapper"><table>
                        <thead><tr><th>ID</th><th>Subject</th><th>Teacher</th><th>Sec</th><th>Group</th><th>Type</th><th>Periods</th><th>Block×Sess</th><th>Room</th><th></th></tr></thead>
                        <tbody>${sess.assignments.map(a => {
                            const c = asgn.catalog[a.subject_id];
                            const label = c ? `${c.short_name ? c.short_name + ' — ' : ''}${c.subject_name}` : a.subject_id;
                            const t = (asgn.teachers || []).find(x => x.teacher_id === a.teacher_id);
                            const teacherLabel = t ? `${t.teacher_name} (${t.department})` : a.teacher_id;
                            return `<tr>
                            <td><code>${a.assignment_id}</code></td>
                            <td title="${a.subject_id}">${label}</td>
                            <td>${teacherLabel}</td>
                            <td>${a.section}</td>
                            <td><span class="badge ${a.group==='ALL'?'badge-blue':'badge-green'}">${a.group}</span></td>
                            <td><span class="badge badge-${a.activity_type==='LECTURE'?'blue':a.activity_type==='PRACTICAL'?'green':'amber'}">${a.activity_type}</span></td>
                            <td>${a.weekly_periods}</td>
                            <td class="text-sm">${a.block_size}×${a.sessions_per_week}</td>
                            <td class="text-sm">${a.room_id || '—'}</td>
                            <td><button class="btn btn-danger btn-sm" onclick="removeAssignment('${a.assignment_id}')">✕</button></td>
                        </tr>`; }).join('')}</tbody>
                    </table></div>`}
                </div>
            </div>
        </div>
        <div class="card mt-24">
            <div class="card-header">
                <h2>Workload Coverage — Section <span id="asgn-sum-section"></span>, Group <span id="asgn-sum-group"></span></h2>
            </div>
            <div class="card-body" id="asgn-summary-box"></div>
        </div>`;

        // Initial cascades
        await asgnFetchSummary();
        renderWorkloadSummaryTable();
        await asgnRefreshTeachers();
        await asgnRefreshRooms();
        asgnUpdateWorkloadDisplay();
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

async function asgnFetchSummary() {
    const section = $('asgn-section')?.value || asgnSectionLabels()[0];
    const group = $('asgn-group')?.value || 'ALL';
    asgn.summary = await api.get(
        `/api/session/${state.session}/workload-summary?section=${encodeURIComponent(section)}&group=${encodeURIComponent(group)}`
    );
    asgn.catalog = {};
    asgn.summary.forEach(e => { asgn.catalog[e.subject_id] = e; });
}

function renderWorkloadSummaryTable() {
    const box = $('asgn-summary-box');
    if (!box) return;
    $('asgn-sum-section').textContent = $('asgn-section').value;
    $('asgn-sum-group').textContent = $('asgn-group').value;
    if (!asgn.summary.length) {
        box.innerHTML = '<p class="text-muted text-sm">No subjects with workloads for this branch/semester.</p>';
        return;
    }
    const cell = (v) => {
        const [req, rem] = v;
        if (req === 0) return '<span class="text-muted">—</span>';
        return rem > 0
            ? `<span>${req - rem}/${req} <span class="badge badge-green">${rem} left</span></span>`
            : `<span>${req}/${req} <span class="badge badge-gray">done</span></span>`;
    };
    box.innerHTML = `<div class="table-wrapper"><table>
        <thead><tr><th>Subject</th><th>Lecture (assigned/required)</th><th>Practical (assigned/required)</th></tr></thead>
        <tbody>${asgn.summary.map(e => `<tr>
            <td><code>${e.subject_id}</code> ${e.subject_code} — ${e.subject_name}</td>
            <td>${cell([e.lecture.required, e.lecture.remaining])}</td>
            <td>${cell([e.practical.required, e.practical.remaining])}</td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}

async function asgnRefreshTeachers() {
    const sel = $('asgn-teacher');
    if (!sel) return;
    const prev = sel.value;
    const branch = asgn.session.branch;
    const semester = asgn.session.semester;
    const subjectId = $('asgn-subject')?.value || '';
    const activity = $('asgn-activity')?.value || '';
    const url = `/api/filters/teachers?branch=${encodeURIComponent(branch)}` +
        (semester ? `&semester=${encodeURIComponent(semester)}` : '') +
        (subjectId ? `&subject_id=${encodeURIComponent(subjectId)}` : '') +
        (activity ? `&activity_type=${encodeURIComponent(activity)}` : '');
    asgn.teachers = await api.get(url);
    sel.innerHTML = '<option value="">Select teacher…</option>' +
        asgn.teachers.map(t => `<option value="${t.teacher_id}">${t.teacher_name} (${t.department})</option>`).join('');
    // Keep the selection only if it is still eligible; never leave a stale option.
    sel.value = asgn.teachers.some(t => t.teacher_id === prev) ? prev : '';
}

async function asgnRefreshRooms() {
    const activity = $('asgn-activity')?.value || 'LECTURE';
    const branch = asgn.session.branch;
    const rooms = await api.get(`/api/filters/rooms?activity=${activity}&branch=${encodeURIComponent(branch)}`);
    const roomSel = $('asgn-room');
    if (!roomSel) return;
    roomSel.innerHTML = '<option value="">No preference</option>' +
        rooms.map(r => `<option value="${r.room_id}">${r.room_name} (${r.room_type})</option>`).join('');
}

function asgnUpdateWorkloadDisplay() {
    const subjectId = $('asgn-subject')?.value || '';
    const activity = $('asgn-activity')?.value || 'LECTURE';
    const entry = asgn.catalog[subjectId];
    const periods = entry
        ? (activity === 'LECTURE' ? entry.lecture.required : entry.practical.required)
        : 0;

    const periodsEl = $('asgn-periods');
    const previewEl = $('asgn-preview');
    const remainingEl = $('asgn-remaining');
    const msgEl = $('asgn-msg');
    const addBtn = $('asgn-add-btn');
    if (!periodsEl) return;

    periodsEl.value = periods > 0 ? periods : '';
    if (entry) {
        previewEl.innerHTML =
            `Lecture workload: <strong>${entry.lecture.required}</strong> · ` +
            `Practical workload: <strong>${entry.practical.required}</strong> · ` +
            `Selected activity (<strong>${activity.toLowerCase()}</strong>): ` +
            `<strong>${periods} periods/week</strong>`;
    } else {
        previewEl.innerHTML = 'Select a subject to see its master workload.';
    }

    const block = parseInt($('asgn-block').value) || 0;
    const sessionsEl = $('asgn-sessions');
    sessionsEl.value = '';
    const remainingElDefault = remainingEl;

    // Validation + clear messages
    let ok = true, msg = '', cls = 'text-muted';
    if (!subjectId) {
        ok = false; msg = 'Select a subject and teacher.';
        remainingElDefault.innerHTML = '';
    } else if (periods <= 0) {
        ok = false; cls = ''; msg = (activity === 'LECTURE' || activity === 'PRACTICAL')
            ? `No ${activity.toLowerCase()} workload exists for this subject.`
            : `Master data has no workload source for ${activity.toLowerCase()} activity — it cannot be assigned.`;
        msg = `<span style="color:var(--error)">${msg}</span>`;
        remainingElDefault.innerHTML = '';
    } else if (!$('asgn-teacher').value) {
        ok = false; msg = 'Select a teacher.';
        remainingElDefault.innerHTML = '';
    } else {
        const assigned = activity === 'LECTURE' ? entry.lecture.assigned : entry.practical.assigned;
        const remaining = periods - assigned;
        const group = $('asgn-group').value;
        const section = $('asgn-section').value;
        remainingEl.innerHTML = remaining > 0
            ? `Remaining (${section} / ${group}): <strong>${remaining}</strong> of ${periods} periods/week`
            : `<span style="color:var(--error)">Fully assigned (${section} / ${group}): ${assigned} of ${periods} periods/week</span>`;
        if (remaining <= 0) {
            ok = false; cls = '';
            msg = `<span style="color:var(--error)">Assignment would exceed the subject's configured workload.</span>`;
        } else if (!block || periods % block !== 0) {
            ok = false; cls = '';
            msg = `<span style="color:var(--error)">Block size × sessions per week does not equal weekly periods (${periods}) — choose a block size that divides ${periods}.</span>`;
        } else {
            sessionsEl.value = periods / block;
            msg = 'Ready to add.';
        }
    }

    msgEl.className = `text-sm ${cls}`;
    msgEl.innerHTML = msg;
    addBtn.disabled = !ok;
}

async function onSectionChange() {
    await asgnFetchSummary();
    renderWorkloadSummaryTable();
    asgnUpdateWorkloadDisplay();
}

async function onGroupChange() {
    await asgnFetchSummary();
    renderWorkloadSummaryTable();
    asgnUpdateWorkloadDisplay();
}

async function onSubjectChange() {
    await asgnRefreshTeachers();   // re-filter eligible teachers for this subject
    asgnUpdateWorkloadDisplay();
}

async function onActivityChange() {
    const activity = $('asgn-activity').value;
    const group = $('asgn-group');
    const block = $('asgn-block');

    // Cascade defaults (mirrors DEFAULT_BLOCK_SIZES in the backend)
    if (activity === 'LECTURE') {
        group.value = 'ALL';
        group.disabled = true;
        block.value = 1;
    } else {
        group.disabled = false;
        if (group.value === 'ALL') group.value = 'G1';
        block.value = asgn.defaultBlocks[activity] || 1;
    }

    await Promise.all([asgnRefreshRooms(), asgnRefreshTeachers()]);
    // Group change may have altered the capacity context → refresh summary
    await asgnFetchSummary();
    renderWorkloadSummaryTable();
    asgnUpdateWorkloadDisplay();
}

async function addAssignment() {
    // weekly_periods is deliberately NOT sent: the server derives it from
    // the master workload, so it cannot be overridden.
    const payload = {
        subject_id: $('asgn-subject').value,
        teacher_id: $('asgn-teacher').value,
        section: $('asgn-section').value,
        group: $('asgn-group').value,
        activity_type: $('asgn-activity').value,
        block_size: parseInt($('asgn-block').value),
        room_id: $('asgn-room').value || null,
    };
    if (!payload.subject_id || !payload.teacher_id) {
        toast('Select subject and teacher', 'error');
        return;
    }
    try {
        await api.post(`/api/session/${state.session}/assignments`, { assignment: payload });
        toast('Assignment added', 'success');
        renderAssignments();  // re-renders form, list, and workload coverage
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function autoAddAssignment() {
    const btn = $('asgn-auto-btn');
    if (btn) btn.disabled = true;
    try {
        const r = await api.post(`/api/session/${state.session}/assignments/auto`, { mode: 'package' });
        if (r.created) {
            toast(`Added: ${r.message}`, 'success');
            renderAssignments();  // refreshes list + coverage immediately
        } else {
            toast(r.message, 'info');
        }
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        const b = $('asgn-auto-btn');
        if (b) b.disabled = false;
    }
}

async function autoFillAssignment() {
    try {
        const r = await api.post(`/api/session/${state.session}/assignments/auto`, { dry_run: true });
        if (!r.proposed) {
            toast(r.message, 'info');
            return;
        }
        const p = r.proposed;
        $('asgn-section').value = p.section;
        $('asgn-subject').value = p.subject_id;
        await asgnRefreshTeachers();
        $('asgn-teacher').value = p.teacher_id;
        $('asgn-activity').value = p.activity_type;
        await asgnRefreshRooms();
        $('asgn-group').value = p.group;
        $('asgn-group').disabled = p.group === 'ALL';
        $('asgn-block').value = p.block_size;
        await asgnFetchSummary();
        renderWorkloadSummaryTable();
        asgnUpdateWorkloadDisplay();
        toast('Form filled with the next valid candidate — review and click Add Assignment.', 'success');
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function removeAssignment(aid) {
    try {
        await api.del(`/api/session/${state.session}/assignments/${aid}`);
        toast('Assignment removed', 'info');
        renderAssignments();
    } catch (e) {
        toast(e.message, 'error');
    }
}

// ================================================================
// Page 6: Room Selection
// ================================================================

async function renderRooms() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const rooms = await api.get('/api/master/rooms');
        const typeGroups = {};
        rooms.forEach(r => {
            if (!typeGroups[r.room_type]) typeGroups[r.room_type] = [];
            typeGroups[r.room_type].push(r);
        });

        content().innerHTML = `
        <div class="page-header">
            <h1>Room Selection</h1>
            <p>Available rooms grouped by type. Active rooms are used during generation.</p>
        </div>
        ${Object.entries(typeGroups).map(([type, rms]) => `
            <div class="card mb-24">
                <div class="card-header">
                    <h2>${type} Rooms</h2>
                    <span class="badge badge-blue">${rms.filter(r => r.active).length} active</span>
                </div>
                <div class="card-body">
                    <div class="table-wrapper"><table>
                        <thead><tr><th>ID</th><th>Name</th><th>Branch</th><th>Shared</th><th>Status</th></tr></thead>
                        <tbody>${rms.map(r => `<tr style="opacity:${r.active ? 1 : 0.5}">
                            <td><code>${r.room_id}</code></td>
                            <td>${r.room_name}</td>
                            <td>${r.branch || '—'}</td>
                            <td>${r.is_shared ? 'Shared' : 'Dedicated'}</td>
                            <td>${r.active ? '<span class="badge badge-green">Active</span>' : '<span class="badge badge-gray">Inactive</span>'}</td>
                        </tr>`).join('')}</tbody>
                    </table></div>
                </div>
            </div>
        `).join('')}
        <div class="flex justify-between">
            <a href="#assignments" class="btn btn-secondary">← Assignments</a>
            <a href="#generate" class="btn btn-primary">Generate Timetable →</a>
        </div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

// ================================================================
// Page 7: Generate Timetable
// ================================================================

async function renderGenerate() {
    if (!sessionGuard()) return;
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const sess = await api.get(`/api/session/${state.session}`);

        content().innerHTML = `
        <div class="page-header">
            <h1>Generate Timetable</h1>
            <p>Session: <strong>${state.session}</strong> — ${sess.branch} Semester ${sess.semester}</p>
        </div>
        <div class="card" style="max-width:640px">
            <div class="card-body text-center">
                <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5" style="margin-bottom:16px">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
                <h3 style="margin-bottom:8px">Ready to Generate</h3>
                <p class="text-muted text-sm mb-24">
                    ${sess.assignments.length} assignment(s) across ${sess.sections.length} section(s)
                </p>
                <div id="gen-status"></div>
                <div class="form-group" style="max-width:260px;margin:0 auto 18px">
                    <label for="gen-seed">Random seed (reproducible)</label>
                    <input type="number" id="gen-seed" value="12345"
                           title="Same seed → same timetable. Change it for a different valid layout.">
                </div>
                <div class="flex gap-8" style="justify-content:center;flex-wrap:wrap">
                    <button id="gen-btn" class="btn btn-primary btn-lg" onclick="runGeneration()">
                        Generate Timetable
                    </button>
                    <button class="btn btn-secondary btn-lg" onclick="runGeneration(true)"
                            title="Generate a different valid timetable with a new random seed">
                        🎲 New Variation
                    </button>
                </div>
            </div>
        </div>
        <div id="gen-result"></div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

async function runGeneration(newVariation = false) {
    const btn = $('gen-btn');
    const statusEl = $('gen-status');
    const seedEl = $('gen-seed');
    if (newVariation && seedEl) {
        seedEl.value = Math.floor(Math.random() * 1000000);
    }
    const rawSeed = seedEl && seedEl.value !== '' ? parseInt(seedEl.value, 10) : NaN;
    const seed = Number.isNaN(rawSeed) ? undefined : rawSeed;

    btn.disabled = true;
    btn.textContent = 'Checking…';
    statusEl.innerHTML = '<div class="spinner"></div>';

    try {
        const check = await api.post(`/api/session/${state.session}/generate`, { mode: 'check' });
        if (check.has_existing && check.existing && check.existing.length > 0) {
            btn.disabled = false;
            btn.textContent = 'Generate Timetable';
            statusEl.innerHTML = '';
            showDuplicateChoiceModal(check.existing, seed);
            return;
        }
    } catch (e) {
        console.warn('Check existing failed, continuing:', e);
    }

    executeGeneration('new_version', seed);
}

function showDuplicateChoiceModal(existing, seed) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'duplicate-choice-modal';
    const names = existing.map(e => `<strong>${htmlEsc(e.display_name)}</strong> (v${e.version})`).join(', ');

    backdrop.innerHTML = `
    <div class="modal-card">
        <div class="modal-header">
            <h3>Timetable Context Exists</h3>
            <button class="modal-close" onclick="$('duplicate-choice-modal').remove()">✕</button>
        </div>
        <div class="modal-body">
            <p style="margin-bottom:14px">
                A persistent timetable already exists for this context:
            </p>
            <div style="background:#f1f5f9;padding:12px;border-radius:var(--radius-md);margin-bottom:16px;font-size:13.5px">
                ${names}
            </div>
            <p style="font-size:13px;color:var(--text-secondary);margin-bottom:18px">
                To prevent accidental loss of data or manual edits, please choose how you want to proceed:
            </p>
            <div class="flex flex-col gap-12">
                <button class="btn btn-primary" onclick="$('duplicate-choice-modal').remove(); executeGeneration('new_version', ${seed})">
                    🌱 Generate New Version (Preserve Existing)
                </button>
                <button class="btn btn-secondary" style="border-color:var(--warning);color:#b45309" onclick="$('duplicate-choice-modal').remove(); executeGeneration('replace_existing', ${seed})">
                    ⚠️ Regenerate / Replace Existing Placements
                </button>
                <button class="btn btn-secondary" onclick="$('duplicate-choice-modal').remove()">
                    Cancel
                </button>
            </div>
        </div>
    </div>`;
    document.body.appendChild(backdrop);
}

async function executeGeneration(mode, seed) {
    const btn = $('gen-btn');
    const statusEl = $('gen-status');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating…';
    }
    if (statusEl) statusEl.innerHTML = '<div class="spinner"></div>';

    try {
        const payload = { mode };
        if (seed !== undefined) payload.seed = seed;
        const result = await api.post(`/api/session/${state.session}/generate`, payload);
        if (btn) {
            btn.textContent = 'Re-Generate';
            btn.disabled = false;
        }
        if (statusEl) statusEl.innerHTML = '';

        if (result.timetable_id) {
            state.timetable = result.timetable_id;
        }

        const scoreColor = result.score >= 80 ? 'var(--success)' : result.score >= 50 ? 'var(--warning)' : 'var(--error)';
        const v = result.validation || {};
        const verdictClass = v.status === 'VALID' ? 'badge-green'
            : v.status === 'NO_VALID_TIMETABLE' ? 'badge-amber' : 'badge-red';
        const usedSeed = (result.stats && result.stats.seed != null) ? result.stats.seed : seed;

        $('gen-result').innerHTML = `
        <div class="stats-grid mt-24">
            <div class="stat-card">
                <div class="stat-icon ${result.is_complete ? 'green' : 'amber'}">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        ${result.is_complete
                            ? '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
                            : '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'}
                    </svg>
                </div>
                <div>
                    <div class="stat-value">${result.is_complete ? 'Complete' : 'Partial'}</div>
                    <div class="stat-label">${result.stats.placed} / ${result.stats.total_sessions} placed</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon blue">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                </div>
                <div>
                    <div class="stat-value" style="color:${scoreColor}">${result.score}</div>
                    <div class="stat-label">Quality Score / 100</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon teal">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                </div>
                <div>
                    <div class="stat-value">${result.stats.teacher_count}</div>
                    <div class="stat-label">Teachers Scheduled</div>
                </div>
            </div>
        </div>
        <div class="flex gap-16 mt-24" style="align-items:center;flex-wrap:wrap">
            <span class="badge ${verdictClass}" style="font-size:13px">
                ${v.headline || (result.is_complete ? 'Complete' : 'Partial')}
            </span>
            <span class="text-muted text-sm">Seed: <strong>${usedSeed}</strong> · Created <strong>${result.timetables ? result.timetables.length : 1}</strong> persistent timetable(s)</span>
        </div>
        <div class="flex gap-16 mt-16">
            <a href="#report" class="btn btn-secondary">View Report</a>
            <a href="#viewer" class="btn btn-primary">View Timetable →</a>
            <a href="#timetables" class="btn btn-secondary">All Timetables</a>
        </div>`;

        toast('Timetable generated & saved to workspace!', 'success');
    } catch (e) {
        if (btn) {
            btn.textContent = 'Retry';
            btn.disabled = false;
        }
        if (statusEl) statusEl.innerHTML = `<p style="color:var(--error);margin-bottom:16px">${e.message}</p>`;
        toast(e.message, 'error');
    }
}

// ================================================================
// Page 8: Conflict / Validation Report
// ================================================================

async function renderReport() {
    content().innerHTML = '<div class="spinner"></div>';
    const reportTab = window._reportActiveTab || 'single';

    try {
        const allTimetables = await api.get('/api/timetables');
        let currentTT = null;
        if (state.timetable) {
            currentTT = allTimetables.find(t => t.timetable_id === state.timetable);
        }
        if (!currentTT && allTimetables.length > 0) {
            currentTT = allTimetables[0];
            state.timetable = currentTT.timetable_id;
        }

        content().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
            <div>
                <h1>Timetable Validation &amp; Quality</h1>
                <p>Verify hard constraints, global clashes, and completeness across timetables</p>
            </div>
            <div class="tabs" style="margin-bottom:0;border-bottom:none">
                <button class="tab ${reportTab==='single'?'active':''}" onclick="switchReportTab('single')">Current Timetable</button>
                <button class="tab ${reportTab==='global'?'active':''}" onclick="switchReportTab('global')">All Timetables (College-Wide)</button>
            </div>
        </div>
        <div id="report-tab-content">
            <div class="spinner"></div>
        </div>`;

        if (reportTab === 'single') {
            await renderSingleTimetableReport(currentTT, allTimetables);
        } else {
            await renderGlobalTimetablesReport();
        }
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error loading report</h3><p>${e.message}</p></div>`;
    }
}

function switchReportTab(tab) {
    window._reportActiveTab = tab;
    renderReport();
}

async function renderSingleTimetableReport(currentTT, allTimetables) {
    const el = $('report-tab-content');
    if (!currentTT) {
        el.innerHTML = `<div class="empty-state"><h3>No Timetables Available</h3><p>Generate a timetable first.</p><a href="#setup" class="btn btn-primary mt-16">Create Timetable</a></div>`;
        return;
    }

    try {
        const report = await api.get(`/api/timetable/${currentTT.timetable_id}/validate`);
        const statusBadge = report.is_valid ? 'badge-green' : 'badge-conflicting';
        const conflicts = report.conflicts || [];

        el.innerHTML = `
        <div class="card mb-24">
            <div class="card-body flex items-center justify-between" style="flex-wrap:wrap;gap:12px">
                <div>
                    <div class="flex items-center gap-12">
                        <h2 style="margin:0;font-size:18px">${htmlEsc(currentTT.display_name)}</h2>
                        <span class="badge ${statusBadge}">${report.status}</span>
                    </div>
                    <p class="text-muted text-sm mt-8">
                        Academic Year: <strong>${htmlEsc(currentTT.academic_year)}</strong> · Version: <strong>v${currentTT.version}</strong>
                    </p>
                </div>
                <div class="flex items-center gap-8">
                    <label style="font-size:12px;font-weight:600">Switch Timetable:</label>
                    <select style="padding:6px 10px;font-size:13px;border:1px solid var(--border);border-radius:var(--radius-md)"
                            onchange="state.timetable=this.value; renderReport()">
                        ${allTimetables.map(t => `<option value="${t.timetable_id}" ${t.timetable_id===currentTT.timetable_id?'selected':''}>${htmlEsc(t.display_name)}</option>`).join('')}
                    </select>
                </div>
            </div>
            ${conflicts.length > 0 ? `
            <div class="card-body" style="border-top:1px solid var(--border)">
                <h3 style="margin-bottom:12px;color:var(--error);font-size:15px">Detected Clashes (${conflicts.length})</h3>
                <div class="table-wrapper"><table>
                    <thead><tr><th>Type</th><th>Day &amp; Period</th><th>Resource</th><th>Conflict Details</th><th>Action</th></tr></thead>
                    <tbody>${conflicts.map(c => `<tr>
                        <td><span class="badge badge-conflicting">${c.conflict_type}</span></td>
                        <td><strong>${c.day} P${c.period}</strong><br><span style="font-size:11px;color:var(--text-muted)">${c.time_label}</span></td>
                        <td><strong>${htmlEsc(c.entity_name || c.entity_id)}</strong></td>
                        <td class="text-sm">${htmlEsc(c.description)}</td>
                        <td>
                            <button class="btn btn-secondary btn-sm" onclick="navigateToConflictTimetable('${currentTT.timetable_id}', '${c.day}', ${c.period})">
                                Jump to Cell
                            </button>
                        </td>
                    </tr>`).join('')}</tbody>
                </table></div>
            </div>` : `
            <div class="card-body" style="border-top:1px solid var(--border);color:var(--success);padding:16px 20px">
                ✓ No clashes detected. This timetable satisfies all hard constraints locally and globally.
            </div>`}
        </div>

        <div class="flex gap-16 mt-24">
            <a href="#viewer" class="btn btn-primary">Open Timetable Grid</a>
            <a href="#timetables" class="btn btn-secondary">Timetables Workspace</a>
            <a href="#export" class="btn btn-secondary">Export</a>
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

async function renderGlobalTimetablesReport() {
    const el = $('report-tab-content');
    try {
        const year = window._wsFilterYear || '2026-27';
        const rep = await api.get(`/api/validation/global?academic_year=${encodeURIComponent(year)}`);
        const statusBadge = rep.is_clean ? 'badge-green' : 'badge-conflicting';
        const conflicts = rep.conflicts || [];

        el.innerHTML = `
        <div class="stats-grid mb-24">
            <div class="stat-card">
                <div class="stat-icon blue">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                </div>
                <div>
                    <div class="stat-value">${rep.total_timetables}</div>
                    <div class="stat-label">Total Timetables (${rep.academic_year})</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon teal">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                </div>
                <div>
                    <div class="stat-value" style="color:${rep.counts.TEACHER > 0 ? 'var(--error)' : 'inherit'}">${rep.counts.TEACHER || 0}</div>
                    <div class="stat-label">Teacher Conflicts</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                </div>
                <div>
                    <div class="stat-value" style="color:${rep.counts.ROOM > 0 ? 'var(--error)' : 'inherit'}">${rep.counts.ROOM || 0}</div>
                    <div class="stat-label">Room Conflicts</div>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-icon amber">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/></svg>
                </div>
                <div>
                    <div class="stat-value" style="color:${(rep.counts.SECTION || 0) + (rep.counts.GROUP || 0) > 0 ? 'var(--error)' : 'inherit'}">
                        ${(rep.counts.SECTION || 0) + (rep.counts.GROUP || 0)}
                    </div>
                    <div class="stat-label">Section / Group Conflicts</div>
                </div>
            </div>
        </div>

        <div class="card mb-24">
            <div class="card-header flex items-center justify-between">
                <div class="flex items-center gap-12">
                    <h2 style="margin:0;font-size:16px">College-Wide Conflict Audit</h2>
                    <span class="badge ${statusBadge}">${rep.status}</span>
                </div>
                <span class="text-muted text-sm">Total Clashes: <strong>${rep.total_conflicts}</strong></span>
            </div>
            <div class="card-body">
                ${conflicts.length === 0 ? `
                    <div style="color:var(--success);padding:12px 0;font-weight:500">
                        ✓ Zero cross-timetable conflicts detected across all ${rep.total_timetables} active timetables for academic year ${rep.academic_year}.
                    </div>
                ` : `
                    <div class="table-wrapper"><table>
                        <thead><tr><th>Type</th><th>Day &amp; Period</th><th>Resource</th><th>Timetable 1</th><th>Timetable 2</th><th>Description</th></tr></thead>
                        <tbody>${conflicts.map(c => {
                            const ttA = c.timetable_a || {};
                            const ttB = c.timetable_b || {};
                            return `<tr>
                                <td><span class="badge badge-conflicting">${c.conflict_type}</span></td>
                                <td><strong>${c.day} P${c.period}</strong><br><span style="font-size:11px;color:var(--text-muted)">${c.time_label}</span></td>
                                <td><strong>${htmlEsc(c.entity_name || c.entity_id)}</strong></td>
                                <td>
                                    ${ttA.timetable_id ? `
                                        <a href="#" class="conflict-link" onclick="navigateToConflictTimetable('${ttA.timetable_id}', '${c.day}', ${c.period});return false">
                                            ${htmlEsc(ttA.display_name || ttA.timetable_id)}
                                        </a><br><span style="font-size:11px;color:var(--text-secondary)">${htmlEsc(ttA.subject_name || '')} (${htmlEsc(ttA.room_name || '')})</span>
                                    ` : '—'}
                                </td>
                                <td>
                                    ${ttB.timetable_id ? `
                                        <a href="#" class="conflict-link" onclick="navigateToConflictTimetable('${ttB.timetable_id}', '${c.day}', ${c.period});return false">
                                            ${htmlEsc(ttB.display_name || ttB.timetable_id)}
                                        </a><br><span style="font-size:11px;color:var(--text-secondary)">${htmlEsc(ttB.subject_name || '')} (${htmlEsc(ttB.room_name || '')})</span>
                                    ` : '—'}
                                </td>
                                <td class="text-sm">${htmlEsc(c.description)}</td>
                            </tr>`;
                        }).join('')}</tbody>
                    </table></div>
                `}
            </div>
        </div>

        <div class="flex gap-16 mt-24">
            <a href="#timetables" class="btn btn-secondary">Timetables Workspace</a>
        </div>`;
    } catch (e) {
        el.innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

function navigateToConflictTimetable(timetableId, day, period) {
    state.timetable = timetableId;
    state.highlightSlot = { day, period };
    location.hash = 'viewer';
}

// ================================================================
// Page 9: Timetable Viewer & Interactive Editor
// ================================================================

async function renderViewer() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const allTimetables = await api.get('/api/timetables');
        if (allTimetables.length === 0) {
            content().innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <h3>No Timetables Available</h3>
                <p>Generate a timetable session first.</p>
                <a href="#setup" class="btn btn-primary mt-16">Create New Timetable</a>
            </div>`;
            return;
        }

        let tt = null;
        if (state.timetable) {
            tt = allTimetables.find(t => t.timetable_id === state.timetable);
        }
        if (!tt) {
            tt = allTimetables[0];
            state.timetable = tt.timetable_id;
        }

        // Fetch full timetable details with placements
        const fullTT = await api.get(`/api/timetable/${tt.timetable_id}`);
        const statusBadge = fullTT.status === 'VALID' ? 'badge-green' :
            fullTT.status === 'CONFLICTING' ? 'badge-conflicting' :
            fullTT.status === 'INCOMPLETE' ? 'badge-incomplete' : 'badge-draft';

        content().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
            <div>
                <div class="flex items-center gap-12">
                    <h1 style="margin:0">${htmlEsc(fullTT.display_name)}</h1>
                    <span class="badge ${statusBadge}">${fullTT.status}</span>
                </div>
                <p style="margin-top:6px">
                    Academic Year: <strong>${htmlEsc(fullTT.academic_year)}</strong> · Context: <code>${htmlEsc(fullTT.context_code)}</code> · Version: <strong>v${fullTT.version}</strong>
                </p>
            </div>
            <div class="flex gap-8 items-center" style="flex-wrap:wrap">
                <select style="padding:6px 12px;font-size:13px;border:1px solid var(--border);border-radius:var(--radius-md);font-weight:600"
                        onchange="switchViewerTimetable(this.value)">
                    ${allTimetables.map(t => `<option value="${t.timetable_id}" ${t.timetable_id===fullTT.timetable_id?'selected':''}>${htmlEsc(t.display_name)}</option>`).join('')}
                </select>
                <button class="btn btn-secondary btn-sm" onclick="undoEdit('${fullTT.timetable_id}')" title="Undo most recent edit">↶ Undo</button>
                <button class="btn btn-secondary btn-sm" onclick="showHistoryModal('${fullTT.timetable_id}')">History</button>
                <a href="#timetables" class="btn btn-secondary btn-sm">Workspace</a>
                <a href="#report" class="btn btn-secondary btn-sm">Report</a>
                <a href="#export" class="btn btn-primary btn-sm">Export →</a>
            </div>
        </div>

        <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:var(--radius-md);padding:10px 16px;margin-bottom:18px;font-size:13px;color:#1e40af;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <span>💡 <strong>Interactive Editor Active:</strong> Click any class cell to edit Subject, Teacher, Room, Day, or Period. Click an empty slot to place a class. Practical blocks move together.</span>
            <span style="font-size:12px;color:#3b82f6">Recess: 1:00 - 2:00 PM is blocked</span>
        </div>

        <div class="timetable-section" id="grid-${fullTT.section}">
            ${renderTimetableGrid(fullTT.placements, fullTT.timetable_id)}
        </div>
        `;

        // Clear highlightSlot after rendering
        if (state.highlightSlot) {
            setTimeout(() => {
                const el = document.querySelector('.slot-chip.has-clash');
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                state.highlightSlot = null;
            }, 300);
        }
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error loading timetable</h3><p>${e.message}</p></div>`;
    }
}

function switchViewerTimetable(id) {
    state.timetable = id;
    renderViewer();
}

function renderTimetableGrid(placements, timetableId) {
    const days = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
    const morningPeriods = [1, 2, 3, 4];
    const afternoonPeriods = [5, 6, 7];
    const timeLabels = {
        1: '9:00 - 10:00',
        2: '10:00 - 11:00',
        3: '11:00 - 12:00',
        4: '12:00 - 1:00',
        5: '2:00 - 3:00',
        6: '3:00 - 4:00',
        7: '4:00 - 5:00'
    };

    const esc = (s) => String(s == null ? '' : s)
        .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

    const grid = {};
    days.forEach(d => { grid[d] = {}; for (let p = 1; p <= 7; p++) grid[d][p] = []; });
    (placements || []).forEach(p => {
        (p.slots || []).forEach(sl => {
            if (grid[sl.day] && grid[sl.day][sl.period]) grid[sl.day][sl.period].push(p);
        });
    });

    const startPeriod = (p) => Math.min(...p.slots.map(s => s.period));
    const blockLen = (p) => p.slots.length;
    const shortOf = (p) => p.short_name || p.subject_short_name || p.subject_code || p.subject_id;

    let html = '<div class="timetable-grid">';
    html += '<div class="grid-header">Day</div>';
    morningPeriods.forEach(p => {
        html += `<div class="grid-header">P${p}<br><span style="font-weight:400;font-size:11px">${timeLabels[p]}</span></div>`;
    });
    html += '<div class="grid-header recess">RECESS<br><span style="font-weight:400;font-size:11px">1:00 - 2:00</span></div>';
    afternoonPeriods.forEach(p => {
        html += `<div class="grid-header">P${p}<br><span style="font-weight:400;font-size:11px">${timeLabels[p]}</span></div>`;
    });

    function renderPeriod(day, pp, covered) {
        if (covered.has(pp)) return '';
        const starts = grid[day][pp].filter(p => startPeriod(p) === pp);
        if (starts.length === 0) {
            return `<div class="grid-cell clickable empty-slot" title="Empty slot (Click to add placement)" onclick="openAddCellModal('${timetableId}', '${day}', ${pp})"></div>`;
        }

        let span = 1;
        starts.forEach(p => { span = Math.max(span, blockLen(p)); });
        for (let k = 1; k < span; k++) covered.add(pp + k);

        const g1 = starts.find(p => p.group === 'G1');
        const g2 = starts.find(p => p.group === 'G2');
        let subject, room, teacher, chipClass, title, isClash = false;

        const isHighlight = state.highlightSlot && state.highlightSlot.day === day && state.highlightSlot.period === pp;

        if (g1 && g2) {
            const s1 = shortOf(g1), s2 = shortOf(g2);
            const t1 = g1.teacher_name || g1.teacher_id;
            const t2 = g2.teacher_name || g2.teacher_id;
            subject = `${s1}/${s2}`;
            room = `${g1.room_name}/${g2.room_name}`;
            teacher = `${t1}/${t2}`;
            chipClass = (g1.activity_type || 'practical').toLowerCase();
            title = `Parallel Practical (Click to edit)\nG1: ${s1} — ${t1} — ${g1.room_name}\nG2: ${s2} — ${t2} — ${g2.room_name}`;
        } else {
            const p = starts[0];
            const s = shortOf(p);
            const t = p.teacher_name || p.teacher_id || '';
            subject = (p.group && p.group !== 'ALL') ? `${s} (${p.group})` : s;
            room = p.room_name || '';
            teacher = t;
            chipClass = (p.activity_type || 'lecture').toLowerCase();
            title = `Click to edit: ${s} (${p.subject_name || p.subject_id}) — ${t} — ${room}`;
        }

        const spanStyle = span > 1 ? ` style="grid-column: span ${span}"` : '';
        const clashClass = isHighlight ? 'has-clash' : '';

        const targetPlacementId = g1 ? g1.placement_id : starts[0].placement_id;

        return `<div class="grid-cell clickable"${spanStyle}>
            <div class="slot-chip editable ${esc(chipClass)} ${clashClass}" title="${esc(title)}"
                 onclick="openEditCellModal('${timetableId}', '${targetPlacementId}', '${day}', ${pp})">
                <div class="chip-subject">${esc(subject)} ${span > 1 ? `(${span}P)` : ''}</div>
                <div class="chip-detail">${esc(room)}</div>
                <div class="chip-detail">${esc(teacher)}</div>
            </div>
        </div>`;
    }

    days.forEach(day => {
        html += `<div class="grid-day">${day}</div>`;
        const covered = new Set();
        morningPeriods.forEach(pp => { html += renderPeriod(day, pp, covered); });
        html += '<div class="grid-cell recess"><span>RECESS</span><span style="font-size:10px;color:#94a3b8">1:00 - 2:00</span></div>';
        afternoonPeriods.forEach(pp => { html += renderPeriod(day, pp, covered); });
    });

    html += '</div>';

    html += `<div class="flex gap-16 mt-16" style="font-size:13px;flex-wrap:wrap">
        <div class="flex items-center gap-8"><div class="slot-chip lecture" style="padding:2px 8px">Lecture</div></div>
        <div class="flex items-center gap-8"><div class="slot-chip practical" style="padding:2px 8px">Practical (G1/G2)</div></div>
        <div class="flex items-center gap-8"><div class="slot-chip workshop" style="padding:2px 8px">Workshop</div></div>
        <div class="flex items-center gap-8"><div class="slot-chip drawing" style="padding:2px 8px">Drawing</div></div>
        <div class="flex items-center gap-8"><span style="color:var(--text-secondary)">Blank&nbsp;=&nbsp;Free period (Click to add class)</span></div>
    </div>`;

    return html;
}

// ================================================================
// Manual Placement Edit / Add Modal
// ================================================================

let _liveValidateTimeout = null;

async function openEditCellModal(timetableId, placementId, day, period) {
    try {
        const tt = await api.get(`/api/timetable/${timetableId}`);
        const p = tt.placements.find(pl => pl.placement_id === placementId);
        if (!p) return;

        const subjects = await api.get(`/api/filters/subjects?branch=${encodeURIComponent(tt.branch)}&semester=${tt.semester}`);
        const rooms = await api.get(`/api/filters/rooms?activity=${p.activity_type}&branch=${encodeURIComponent(tt.branch)}`);
        const teachers = await api.get(`/api/filters/teachers?branch=${encodeURIComponent(tt.branch)}&semester=${tt.semester}&subject_id=${encodeURIComponent(p.subject_id)}&activity_type=${p.activity_type}`);

        let partner = null;
        if (p.is_linked_parallel && p.linked_placement_id) {
            partner = tt.placements.find(pl => pl.placement_id === p.linked_placement_id);
        }

        renderCellEditorModal({
            timetableId,
            placementId,
            isNew: false,
            tt,
            p,
            partner,
            subjects,
            rooms,
            teachers,
            initialDay: day,
            initialPeriod: period,
        });
    } catch (e) {
        toast(`Error opening editor: ${e.message}`, 'error');
    }
}

async function openAddCellModal(timetableId, day, period) {
    try {
        const tt = await api.get(`/api/timetable/${timetableId}`);
        const subjects = await api.get(`/api/filters/subjects?branch=${encodeURIComponent(tt.branch)}&semester=${tt.semester}`);
        const rooms = await api.get(`/api/filters/rooms?activity=LECTURE&branch=${encodeURIComponent(tt.branch)}`);
        const teachers = await api.get(`/api/filters/teachers?branch=${encodeURIComponent(tt.branch)}&semester=${tt.semester}&activity_type=LECTURE`);

        renderCellEditorModal({
            timetableId,
            placementId: '',
            isNew: true,
            tt,
            p: {
                subject_id: subjects[0]?.subject_id || '',
                teacher_id: teachers[0]?.teacher_id || '',
                room_id: rooms[0]?.room_id || '',
                activity_type: 'LECTURE',
                group: 'ALL',
                block_size: 1,
            },
            partner: null,
            subjects,
            rooms,
            teachers,
            initialDay: day,
            initialPeriod: period,
        });
    } catch (e) {
        toast(`Error opening editor: ${e.message}`, 'error');
    }
}

function renderCellEditorModal(opts) {
    $('cell-editor-modal')?.remove();

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.id = 'cell-editor-modal';

    const days = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
    const periods = [
        { num: 1, label: 'P1 (9:00 - 10:00)' },
        { num: 2, label: 'P2 (10:00 - 11:00)' },
        { num: 3, label: 'P3 (11:00 - 12:00)' },
        { num: 4, label: 'P4 (12:00 - 1:00)' },
        { num: 5, label: 'P5 (2:00 - 3:00)' },
        { num: 6, label: 'P6 (3:00 - 4:00)' },
        { num: 7, label: 'P7 (4:00 - 5:00)' },
    ];

    backdrop.innerHTML = `
    <div class="modal-card">
        <div class="modal-header">
            <h3>${opts.isNew ? 'Add Placement' : 'Edit Placement'} — ${htmlEsc(opts.tt.display_name)}</h3>
            <button class="modal-close" onclick="$('cell-editor-modal').remove()">✕</button>
        </div>
        <div class="modal-body">
            <div id="modal-conflict-alert" class="conflict-alert clean" style="margin-bottom:16px">
                ✓ No clashes detected for this proposed slot across college timetables.
            </div>

            ${opts.partner ? `
            <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:var(--radius-md);padding:12px;margin-bottom:16px;font-size:13px;color:#166534">
                <strong>🔗 Linked Parallel Practical (${opts.p.group} &amp; ${opts.partner.group}):</strong>
                Partner: ${htmlEsc(opts.partner.teacher_name || opts.partner.teacher_id)} in Room ${htmlEsc(opts.partner.room_name || opts.partner.room_id)}.
                <div style="margin-top:6px">
                    <label style="cursor:pointer">
                        <input type="checkbox" id="modal-sync-partner" checked>
                        Keep both groups synchronized at the same day &amp; periods (Recommended)
                    </label>
                </div>
            </div>` : ''}

            ${opts.p.block_size > 1 ? `
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:var(--radius-md);padding:10px 14px;margin-bottom:16px;font-size:13px;color:#1e40af">
                <strong>📦 Multi-period Practical Block (${opts.p.block_size} periods):</strong>
                Moving this slot moves the complete ${opts.p.block_size}-period block together without splitting.
            </div>` : ''}

            <div class="form-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
                <div class="form-group" style="grid-column: span 2">
                    <label>Subject</label>
                    <select id="modal-subject" onchange="onModalSubjectChange('${opts.timetableId}')">
                        ${opts.subjects.map(s => `
                            <option value="${s.subject_id}" ${s.subject_id===opts.p.subject_id?'selected':''}>
                                ${htmlEsc(s.short_name || s.subject_code)} — ${htmlEsc(s.subject_name)}
                            </option>
                        `).join('')}
                    </select>
                </div>

                <div class="form-group">
                    <label>Teacher</label>
                    <select id="modal-teacher" onchange="triggerLiveValidation('${opts.timetableId}')">
                        ${opts.teachers.map(t => `
                            <option value="${t.teacher_id}" ${t.teacher_id===opts.p.teacher_id?'selected':''}>
                                ${htmlEsc(t.teacher_name || t.teacher_id)} (${t.department})
                            </option>
                        `).join('')}
                    </select>
                </div>

                <div class="form-group">
                    <label>Room</label>
                    <select id="modal-room" onchange="triggerLiveValidation('${opts.timetableId}')">
                        ${opts.rooms.map(r => `
                            <option value="${r.room_id}" ${r.room_id===opts.p.room_id?'selected':''}>
                                ${htmlEsc(r.room_name || r.room_id)} (${r.room_type})
                            </option>
                        `).join('')}
                    </select>
                </div>

                <div class="form-group">
                    <label>Day</label>
                    <select id="modal-day" onchange="triggerLiveValidation('${opts.timetableId}')">
                        ${days.map(d => `<option value="${d}" ${d===opts.initialDay?'selected':''}>${d}</option>`).join('')}
                    </select>
                </div>

                <div class="form-group">
                    <label>Starting Period</label>
                    <select id="modal-period" onchange="triggerLiveValidation('${opts.timetableId}')">
                        ${periods.map(pr => `
                            <option value="${pr.num}" ${pr.num===opts.initialPeriod?'selected':''}>
                                ${pr.label}
                            </option>
                        `).join('')}
                    </select>
                </div>

                <div class="form-group">
                    <label>Group</label>
                    <select id="modal-group" onchange="triggerLiveValidation('${opts.timetableId}')">
                        <option value="ALL" ${opts.p.group==='ALL'?'selected':''}>Whole Section (ALL)</option>
                        <option value="G1" ${opts.p.group==='G1'?'selected':''}>Group 1 (G1)</option>
                        <option value="G2" ${opts.p.group==='G2'?'selected':''}>Group 2 (G2)</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Activity Type</label>
                    <select id="modal-activity" onchange="onModalActivityChange('${opts.timetableId}')">
                        <option value="LECTURE" ${opts.p.activity_type==='LECTURE'?'selected':''}>Lecture</option>
                        <option value="PRACTICAL" ${opts.p.activity_type==='PRACTICAL'?'selected':''}>Practical</option>
                        <option value="WORKSHOP" ${opts.p.activity_type==='WORKSHOP'?'selected':''}>Workshop</option>
                        <option value="DRAWING" ${opts.p.activity_type==='DRAWING'?'selected':''}>Drawing</option>
                    </select>
                </div>
            </div>
        </div>
        <div class="modal-footer">
            ${!opts.isNew ? `
                <button class="btn btn-secondary" style="color:var(--error);border-color:var(--border);margin-right:auto"
                        onclick="deletePlacementAction('${opts.timetableId}', '${opts.placementId}')">
                    Remove Class
                </button>
            ` : ''}
            <button class="btn btn-secondary" onclick="$('cell-editor-modal').remove()">Cancel</button>
            <button id="modal-save-btn" class="btn btn-primary"
                    onclick="savePlacementEdit('${opts.timetableId}', '${opts.placementId}')">
                Save Changes
            </button>
        </div>
    </div>`;

    document.body.appendChild(backdrop);
    triggerLiveValidation(opts.timetableId, opts.placementId);
}

async function onModalSubjectChange(timetableId) {
    const subjId = $('modal-subject')?.value;
    const act = $('modal-activity')?.value || 'LECTURE';
    const tt = await api.get(`/api/timetable/${timetableId}`);
    try {
        const teachers = await api.get(`/api/filters/teachers?branch=${encodeURIComponent(tt.branch)}&semester=${tt.semester}&subject_id=${encodeURIComponent(subjId)}&activity_type=${act}`);
        const tSel = $('modal-teacher');
        if (tSel && teachers.length > 0) {
            tSel.innerHTML = teachers.map(t => `<option value="${t.teacher_id}">${htmlEsc(t.teacher_name || t.teacher_id)} (${t.department})</option>`).join('');
        }
    } catch (e) {}
    triggerLiveValidation(timetableId);
}

async function onModalActivityChange(timetableId) {
    const act = $('modal-activity')?.value || 'LECTURE';
    const tt = await api.get(`/api/timetable/${timetableId}`);
    try {
        const rooms = await api.get(`/api/filters/rooms?activity=${act}&branch=${encodeURIComponent(tt.branch)}`);
        const rSel = $('modal-room');
        if (rSel && rooms.length > 0) {
            rSel.innerHTML = rooms.map(r => `<option value="${r.room_id}">${htmlEsc(r.room_name || r.room_id)} (${r.room_type})</option>`).join('');
        }
    } catch (e) {}
    triggerLiveValidation(timetableId);
}

function triggerLiveValidation(timetableId, placementId) {
    clearTimeout(_liveValidateTimeout);
    _liveValidateTimeout = setTimeout(async () => {
        const alertEl = $('modal-conflict-alert');
        const saveBtn = $('modal-save-btn');
        if (!alertEl) return;

        const candidate = {
            placement_id: placementId || '',
            subject_id: $('modal-subject')?.value || '',
            teacher_id: $('modal-teacher')?.value || '',
            room_id: $('modal-room')?.value || '',
            day: $('modal-day')?.value || 'MON',
            period: parseInt($('modal-period')?.value || '1', 10),
            group: $('modal-group')?.value || 'ALL',
            activity_type: $('modal-activity')?.value || 'LECTURE',
        };

        try {
            const res = await api.post(`/api/timetable/${timetableId}/check-conflict`, candidate);
            if (res.has_conflict && res.conflicts.length > 0) {
                alertEl.className = 'conflict-alert';
                alertEl.innerHTML = `<strong>⚠️ Conflict Detected:</strong><br>${res.conflicts.map(c => htmlEsc(c.description)).join('<br>')}`;
                if (saveBtn) {
                    saveBtn.textContent = 'Save with Override (Conflicting)';
                    saveBtn.style.background = 'var(--error)';
                }
            } else {
                alertEl.className = 'conflict-alert clean';
                alertEl.innerHTML = '✓ No clashes detected for this slot across college timetables.';
                if (saveBtn) {
                    saveBtn.textContent = 'Save Changes';
                    saveBtn.style.background = '';
                }
            }
        } catch (e) {
            console.warn('Live validation failed:', e);
        }
    }, 250);
}

async function savePlacementEdit(timetableId, placementId, forceOverride = false) {
    const saveBtn = $('modal-save-btn');
    const alertEl = $('modal-conflict-alert');
    const hasConflict = alertEl && !alertEl.classList.contains('clean');

    const placementData = {
        placement_id: placementId || '',
        subject_id: $('modal-subject')?.value || '',
        teacher_id: $('modal-teacher')?.value || '',
        room_id: $('modal-room')?.value || '',
        day: $('modal-day')?.value || 'MON',
        period: parseInt($('modal-period')?.value || '1', 10),
        group: $('modal-group')?.value || 'ALL',
        activity_type: $('modal-activity')?.value || 'LECTURE',
    };

    const movePartner = $('modal-sync-partner') ? $('modal-sync-partner').checked : true;

    try {
        const payload = {
            placement: placementData,
            force_override: forceOverride || hasConflict,
            move_partner: movePartner,
        };

        const res = await api.post(`/api/timetable/${timetableId}/placement/save`, payload);
        toast(res.has_conflict ? 'Saved with conflict override (Conflicting)' : 'Placement updated successfully', res.has_conflict ? 'error' : 'success');
        $('cell-editor-modal')?.remove();
        renderViewer();
    } catch (e) {
        toast(`Save failed: ${e.message}`, 'error');
    }
}

async function deletePlacementAction(timetableId, placementId) {
    if (!confirm('Are you sure you want to clear this class? The period will become FREE.')) return;
    try {
        await api.del(`/api/timetable/${timetableId}/placement/${placementId}`);
        toast('Class removed (period is now free)', 'success');
        $('cell-editor-modal')?.remove();
        renderViewer();
    } catch (e) {
        toast(`Failed to remove class: ${e.message}`, 'error');
    }
}

async function undoEdit(timetableId) {
    try {
        const res = await api.post(`/api/timetable/${timetableId}/undo`, {});
        toast('Reverted last edit', 'success');
        renderViewer();
    } catch (e) {
        toast(`Undo failed: ${e.message}`, 'error');
    }
}

async function showHistoryModal(timetableId) {
    try {
        const tt = await api.get(`/api/timetable/${timetableId}`);
        const history = tt.history || [];

        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop';
        backdrop.id = 'history-modal';

        backdrop.innerHTML = `
        <div class="modal-card">
            <div class="modal-header">
                <h3>Version History &amp; Audit Trail</h3>
                <button class="modal-close" onclick="$('history-modal').remove()">✕</button>
            </div>
            <div class="modal-body">
                <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">
                    Audit log for <strong>${htmlEsc(tt.display_name)}</strong> (Current: v${tt.version})
                </p>
                ${history.length === 0 ? '<p class="text-muted text-sm">No history records.</p>' : `
                    <div class="flex flex-col gap-12">
                        ${history.slice().reverse().map(h => `
                            <div style="background:#f8fafc;border:1px solid var(--border);border-radius:var(--radius-md);padding:12px 16px">
                                <div class="flex justify-between items-center mb-4">
                                    <span class="badge ${h.action==='CREATED'?'badge-green':h.action==='OVERRIDE'?'badge-conflicting':'badge-blue'}">
                                        v${h.version} · ${h.action}
                                    </span>
                                    <span style="font-size:11px;color:var(--text-muted)">${h.timestamp ? h.timestamp.replace('T', ' ') : '—'}</span>
                                </div>
                                <div style="font-size:13.5px;font-weight:500;color:var(--text)">${htmlEsc(h.description)}</div>
                            </div>
                        `).join('')}
                    </div>
                `}
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="$('history-modal').remove()">Close</button>
            </div>
        </div>`;
        document.body.appendChild(backdrop);
    } catch (e) {
        toast(`Error loading history: ${e.message}`, 'error');
    }
}

// ================================================================
// Page 10: Export Timetable
// ================================================================

const EXPORT_FORMATS = ['pdf', 'xlsx', 'csv'];

async function renderExport() {
    content().innerHTML = '<div class="spinner"></div>';
    try {
        const allTimetables = await api.get('/api/timetables');
        if (allTimetables.length === 0) {
            content().innerHTML = `
            <div class="empty-state">
                <h3>No timetable to export</h3>
                <p>Generate a timetable first.</p>
                <a href="#setup" class="btn btn-primary mt-16">Generate</a>
            </div>`;
            return;
        }

        let tt = null;
        if (state.timetable) {
            tt = allTimetables.find(t => t.timetable_id === state.timetable);
        }
        if (!tt) {
            tt = allTimetables[0];
            state.timetable = tt.timetable_id;
        }

        const info = await api.get(`/api/timetable/${tt.timetable_id}/export/info`);

        const conflictBanner = info.is_clean
            ? `<div class="card" style="border-left:4px solid #28a745;margin-bottom:16px">
                   <div class="card-body" style="padding:12px 16px;color:#155724">
                       <strong>✓ Conflict audit passed</strong> — all placements satisfy the hard
                       constraints locally and globally across the college.
                   </div>
               </div>`
            : `<div class="card" style="border-left:4px solid #dc3545;margin-bottom:16px">
                   <div class="card-body" style="padding:12px 16px;color:#721c24">
                       <strong>⚠ Export contains a timetable with unresolved conflicts (${info.conflict_total} total).</strong>
                       ${info.global_conflicts && info.global_conflicts.length > 0 ? `<br><span style="font-size:12.5px">${info.global_conflicts.map(c => htmlEsc(c.description)).join('<br>')}</span>` : ''}
                   </div>
               </div>`;

        const viewRows = (info.views || []).map(v => `
            <tr>
                <td>
                    <div style="font-weight:600">${v.title}</div>
                    <div style="font-size:12px;color:#888">${v.entities.length} schedule(s)</div>
                </td>
                <td style="text-align:right;white-space:nowrap">
                    ${EXPORT_FORMATS.map(f => `
                        <button class="btn btn-sm ${f === 'pdf' ? 'btn-primary' : 'btn-secondary'}" style="margin-left:6px"
                                onclick="downloadTimetableExport('${tt.timetable_id}', '${v.kind}', '${f}')">${f.toUpperCase()}</button>
                    `).join('')}
                </td>
            </tr>`).join('');

        content().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
            <div>
                <h1>Export Timetable</h1>
                <p>Export official deliverables for: <strong>${htmlEsc(tt.display_name)}</strong> (${htmlEsc(tt.academic_year)})</p>
            </div>
            <div class="flex items-center gap-8">
                <label style="font-size:12px;font-weight:600">Selected Timetable:</label>
                <select style="padding:6px 12px;font-size:13px;border:1px solid var(--border);border-radius:var(--radius-md)"
                        onchange="state.timetable=this.value; renderExport()">
                    ${allTimetables.map(t => `<option value="${t.timetable_id}" ${t.timetable_id===tt.timetable_id?'selected':''}>${htmlEsc(t.display_name)}</option>`).join('')}
                </select>
            </div>
        </div>

        ${conflictBanner}

        <div class="card" style="margin-bottom:20px;border:2px solid var(--primary-500);background:linear-gradient(to right, #f8fafc, #ffffff)">
            <div class="card-body" style="padding:20px">
                <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:16px">
                    <div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <h2 style="margin:0;font-size:18px;color:#1F3864">Official College Layout</h2>
                            <span class="badge badge-green" style="font-size:11px">Selected Timetable Only</span>
                        </div>
                        <p style="margin:4px 0 0 0;font-size:13px;color:#64748b">
                            Standard layout: <code>DAY | TIME | PERIOD | SUBJECT | ROOM | TEACHER</code> with recess and block spans.
                        </p>
                    </div>
                    <div class="flex gap-8" style="flex-wrap:nowrap">
                        <button class="btn btn-primary" onclick="downloadTimetableCollegeExport('${tt.timetable_id}', 'xlsx')">Download XLSX</button>
                        <button class="btn btn-primary" onclick="downloadTimetableCollegeExport('${tt.timetable_id}', 'pdf')">Download PDF</button>
                        <button class="btn btn-secondary" onclick="downloadTimetableCollegeExport('${tt.timetable_id}', 'csv')">Download CSV</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="card" style="margin-bottom:16px">
            <div class="card-header"><h3 style="margin:0;font-size:15px">All Entity Grid Views</h3></div>
            <div class="card-body">
                <table style="width:100%;border-collapse:collapse">${viewRows}</table>
            </div>
        </div>

        <div class="card">
            <div class="card-body">
                <h3 style="margin-bottom:8px">Save Complete Bundle</h3>
                <p style="font-size:13px;color:#666;margin-bottom:12px">
                    Writes views in all three formats to <code>Data/timetables/${tt.timetable_id}/exports/</code>.
                </p>
                <button class="btn btn-primary" onclick="saveTimetableAllExports('${tt.timetable_id}')">Export Complete Bundle</button>
                <span id="save-tt-export-status" style="margin-left:12px;font-size:13px"></span>
            </div>
        </div>

        <div class="flex gap-16 mt-24">
            <a href="#viewer" class="btn btn-secondary">← Back to Timetable Viewer</a>
            <a href="#timetables" class="btn btn-secondary">Timetables Workspace</a>
        </div>`;
    } catch (e) {
        content().innerHTML = `<div class="empty-state"><h3>Error</h3><p>${e.message}</p></div>`;
    }
}

function downloadTimetableExport(timetableId, viewKind, fmt) {
    const url = `/api/timetable/${timetableId}/export/${viewKind}/${fmt}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`Preparing ${fmt.toUpperCase()} export…`, 'success');
}

function downloadTimetableCollegeExport(timetableId, fmt) {
    const url = `/api/timetable/${timetableId}/export/college/${fmt}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`Preparing official ${fmt.toUpperCase()} export…`, 'success');
}

async function saveTimetableAllExports(timetableId) {
    const status = document.getElementById('save-tt-export-status');
    if (status) status.textContent = 'Exporting…';
    try {
        const res = await api.post(`/api/timetable/${timetableId}/export/save`, {});
        if (status) {
            status.innerHTML = res.is_clean
                ? `<span style="color:#28a745">✓ ${res.files.length} files written to ${res.directory}</span>`
                : `<span style="color:#dc3545">✓ ${res.files.length} files written — ${res.conflict_total} conflict(s) flagged.</span>`;
        }
        toast('Bundle exported successfully', 'success');
    } catch (e) {
        if (status) status.innerHTML = `<span style="color:#dc3545">Export failed: ${e.message}</span>`;
        toast(e.message, 'error');
    }
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

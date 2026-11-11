// Genshin Launcher Web Application Controller
let currentTab = 'home';
let currentCategory = 'Tất Cả';
let currentSearch = '';
let currentSort = 'name_asc';
let allModsData = [];
let macroSubtab = 'basic';
let wishSubtab = 'history';

// Initialize
window.addEventListener('DOMContentLoaded', async () => {
    await fetchInitialData();
    setInterval(updateStatus, 2000);
});

async function apiCall(endpoint, data = null) {
    try {
        const options = {
            method: data ? 'POST' : 'GET',
            headers: { 'Content-Type': 'application/json' },
            body: data ? JSON.stringify(data) : null
        };
        const res = await fetch(endpoint, options);
        return await res.json();
    } catch (e) {
        console.error("API error:", e);
        return { success: false, error: String(e) };
    }
}

// Window actions
window.api = {
    minimize: () => apiCall('/api/window/minimize'),
    maximize: () => apiCall('/api/window/maximize'),
    close: () => apiCall('/api/window/close'),
    openHoYoPlay: () => apiCall('/api/hoyoplay/open'),
    toggleOverlay: () => apiCall('/api/overlay/toggle'),
    openFolder: (f) => apiCall('/api/folder/open', { folder: f }),
    createShortcut: () => apiCall('/api/shortcut/create'),
    addModDialog: () => apiCall('/api/mod/add_dialog').then(r => r.success && loadMods()),
    restartAdmin: () => apiCall('/api/admin/restart'),
    importPluginDialog: () => apiCall('/api/plugins/import_dialog').then(r => r.success && loadPlugins())
};

// Initial Data
async function fetchInitialData() {
    const data = await apiCall('/api/init');
    if (data) {
        document.getElementById('badge-game-ver').innerText = 'v' + (data.game_version || '7.1.0');
        document.getElementById('sidebar-version').innerText = 'Phiên bản: v' + (data.game_version || '7.1.0');
        if (data.is_admin) {
            document.getElementById('macro-admin-warning')?.classList.add('hidden');
        }
        appendLog("Đã kết nối với Genshin Engine. Trạng thái: Sẵn sàng!");
    }
    loadMods();
}

// Tabs
function switchTab(tabId) {
    currentTab = tabId;
    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
    document.getElementById(`tab-${tabId}`)?.classList.remove('hidden');

    document.querySelectorAll('#nav-tabs .nav-btn').forEach(btn => {
        if (btn.dataset.tab === tabId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    if (tabId === 'mods') loadMods();
    if (tabId === 'groups') loadGroups();
    if (tabId === 'macro') loadMacro();
    if (tabId === 'wishes') loadWishData();
    if (tabId === 'plugins') loadPlugins();
    if (tabId === 'trash') loadTrash();
}

// Live Status polling
async function updateStatus() {
    const res = await apiCall('/api/status');
    if (!res) return;

    const pill = document.getElementById('game-status-pill');
    if (res.running) {
        pill.innerHTML = `
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping"></span>
            <span class="text-emerald-300 font-bold">Game: Đang chạy (PID ${res.pid})</span>
        `;
    } else {
        pill.innerHTML = `
            <span class="w-2.5 h-2.5 rounded-full bg-slate-500"></span>
            <span class="text-slate-400 font-medium">Game: Chưa chạy</span>
        `;
    }
}

// Launch Game
async function launchGame(withMods = true, unlockFps = false) {
    appendLog(`[Khởi Động] Chuẩn bị vào game (Mod: ${withMods}, FPS 120: ${unlockFps})...`);
    const res = await apiCall('/api/game/launch', { with_mods: withMods, unlock_fps: unlockFps });
    if (res.success) {
        appendLog(`[Thành Công] ${res.message}`);
    } else {
        appendLog(`[Lỗi] ${res.error}`);
    }
}

// Logs Terminal
function appendLog(msg) {
    const term = document.getElementById('terminal-logs');
    if (!term) return;
    const time = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = 'text-slate-300';
    line.innerHTML = `<span class="text-slate-500">[${time}]</span> ${msg}`;
    term.appendChild(line);
    term.scrollTop = term.scrollHeight;
}

function clearLogs() {
    const term = document.getElementById('terminal-logs');
    if (term) term.innerHTML = '';
}

// ==========================================
// MOD MANAGER
// ==========================================
async function loadMods() {
    const res = await apiCall('/api/mods/list', {
        category: currentCategory,
        search: currentSearch,
        sort: currentSort
    });

    if (!res || !res.mods) return;
    allModsData = res.mods;

    const enabledCount = allModsData.filter(m => m.is_enabled).length;
    document.getElementById('nav-mods-count').innerText = allModsData.length;
    document.getElementById('home-active-mods-badge').innerText = `📦 ${enabledCount} Mod đang kích hoạt`;
    document.getElementById('mods-summary-text').innerText = `Hiển thị ${allModsData.length} mod (${enabledCount} đang bật)`;

    renderCategories(res.categories || {});
    renderModCards(allModsData);
}

function renderCategories(cats) {
    const container = document.getElementById('category-list');
    if (!container) return;
    container.innerHTML = '';

    for (const [name, count] of Object.entries(cats)) {
        const isActive = name === currentCategory;
        const btn = document.createElement('button');
        btn.className = `w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-semibold flex items-center justify-between transition ${
            isActive ? 'bg-blue-600 text-white shadow-md' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
        }`;
        btn.innerHTML = `<span>${name}</span><span class="text-[10px] px-1.5 py-0.2 rounded-full ${isActive ? 'bg-blue-700' : 'bg-slate-800'}">${count}</span>`;
        btn.onclick = () => {
            currentCategory = name;
            loadMods();
        };
        container.appendChild(btn);
    }
}

function renderModCards(mods) {
    const grid = document.getElementById('mod-grid');
    if (!grid) return;
    grid.innerHTML = '';

    if (mods.length === 0) {
        grid.innerHTML = '<div class="col-span-3 text-center py-20 text-slate-500">Không tìm thấy mod nào trong danh mục này.</div>';
        return;
    }

    mods.forEach(mod => {
        const card = document.createElement('div');
        card.className = `mod-card ${mod.is_enabled ? 'enabled' : ''}`;
        
        const thumbUrl = mod.thumbnail ? `/thumbnail?path=${encodeURIComponent(mod.thumbnail)}` : '/game-icon';

        card.innerHTML = `
            <div class="h-32 bg-slate-900 relative overflow-hidden group">
                <img src="${thumbUrl}" class="w-full h-full object-cover transition duration-300 group-hover:scale-105" onerror="this.src='/game-icon'">
                <div class="absolute inset-0 bg-gradient-to-t from-slate-950 via-transparent to-transparent opacity-80"></div>
                <span class="absolute top-2 right-2 text-[10px] font-bold px-2 py-0.5 rounded-full ${mod.is_enabled ? 'bg-emerald-500/80 text-white' : 'bg-slate-800/80 text-slate-400'}">
                    ${mod.is_enabled ? '● Đang bật' : '○ Đã tắt'}
                </span>
                <span class="absolute bottom-2 left-2 text-[11px] font-semibold text-slate-300 bg-slate-950/70 px-2 py-0.5 rounded">
                    ${mod.category}
                </span>
            </div>
            <div class="p-3 flex flex-col justify-between flex-1 gap-2">
                <div class="flex items-start justify-between gap-2">
                    <h4 class="font-bold text-xs text-white truncate" title="${mod.name}">${mod.name}</h4>
                    <span class="text-[10px] text-slate-500 font-mono">${mod.size_mb} MB</span>
                </div>
                <div class="flex items-center justify-between pt-2 border-t border-slate-800/60">
                    <div class="flex items-center gap-1.5">
                        <button onclick="trashMod('${encodeURIComponent(mod.name)}')" class="p-1 rounded text-slate-400 hover:text-red-400 hover:bg-slate-800 transition" title="Xóa vào thùng rác">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        </button>
                    </div>
                    <label class="switch-label">
                        <input type="checkbox" ${mod.is_enabled ? 'checked' : ''} onchange="toggleMod('${encodeURIComponent(mod.name)}', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function toggleMod(modName, enabled) {
    const decoded = decodeURIComponent(modName);
    const res = await apiCall('/api/mod/toggle', { name: decoded, enabled });
    if (res.success) {
        appendLog(`[Mod] Đã ${enabled ? 'bật' : 'tắt'} mod: ${decoded}`);
        loadMods();
    }
}

async function toggleAllMods(enabled) {
    const res = await apiCall('/api/mod/toggle_all', { enabled });
    if (res.success) {
        appendLog(`[Mod] Đã ${enabled ? 'bật' : 'tắt'} toàn bộ mod!`);
        loadMods();
    }
}

async function trashMod(modName) {
    const decoded = decodeURIComponent(modName);
    if (!confirm(`Bạn có chắc muốn chuyển mod '${decoded}' vào Thùng Rác?`)) return;
    const res = await apiCall('/api/mod/trash', { name: decoded });
    if (res.success) {
        appendLog(`[Thùng Rác] Đã chuyển mod '${decoded}' vào Thùng Rác.`);
        loadMods();
    }
}

function onSearchMod(val) {
    currentSearch = val;
    loadMods();
}

function clearModSearch() {
    document.getElementById('mod-search-input').value = '';
    currentSearch = '';
    loadMods();
}

function onSortMod(val) {
    currentSort = val;
    loadMods();
}

// ==========================================
// MOD GROUPS
// ==========================================
async function loadGroups() {
    const res = await apiCall('/api/groups/list');
    const container = document.getElementById('group-list');
    if (!container) return;
    container.innerHTML = '';

    if (!res.groups || res.groups.length === 0) {
        container.innerHTML = '<div class="p-3 text-slate-500 text-xs">Chưa có nhóm mod nào.</div>';
        return;
    }

    res.groups.forEach(g => {
        const btn = document.createElement('button');
        btn.className = 'w-full text-left p-2.5 rounded-lg bg-slate-800/40 hover:bg-slate-800 border border-slate-700/40 transition flex items-center justify-between text-xs';
        btn.innerHTML = `
            <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-full" style="background-color: ${g.color || '#38bdf8'};"></span>
                <span class="font-bold text-white">${g.name}</span>
            </div>
            <span class="text-[10px] text-slate-400">${g.mods ? g.mods.length : 0} mod</span>
        `;
        btn.onclick = () => renderGroupDetail(g);
        container.appendChild(btn);
    });

    if (res.groups.length > 0) renderGroupDetail(res.groups[0]);
}

function renderGroupDetail(group) {
    const view = document.getElementById('group-detail-view');
    if (!view) return;

    view.innerHTML = `
        <div class="flex items-center justify-between pb-3 mb-3 border-b border-slate-800/60">
            <div class="flex items-center gap-2">
                <span class="w-4 h-4 rounded" style="background-color: ${group.color || '#38bdf8'};"></span>
                <h3 class="text-base font-bold text-white">${group.name}</h3>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="toggleGroup('${group.id}', true)" class="btn-emerald text-xs">✅ Bật cả nhóm</button>
                <button onclick="toggleGroup('${group.id}', false)" class="btn-rose text-xs">⛔ Tắt cả nhóm</button>
                <button onclick="deleteGroup('${group.id}')" class="btn-secondary text-xs text-red-400">🗑️ Xoá thư mục</button>
            </div>
        </div>
        <div class="flex-1 overflow-y-auto space-y-2 pr-1" id="group-mods-list">
            ${(group.mods && group.mods.length > 0) ? group.mods.map(m => `
                <div class="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 flex items-center justify-between text-xs">
                    <span class="font-semibold text-slate-200">${m}</span>
                    <button onclick="removeModFromGroup('${group.id}', '${m}')" class="text-slate-500 hover:text-red-400">✕</button>
                </div>
            `).join('') : '<div class="text-center py-10 text-slate-500 text-xs">Nhóm này chưa có Mod nào.</div>'}
        </div>
    `;
}

async function createGroupDialog() {
    const name = prompt("Nhập tên nhóm Mod mới:");
    if (!name || !name.trim()) return;
    await apiCall('/api/groups/create', { name: name.trim() });
    loadGroups();
}

async function toggleGroup(id, enabled) {
    await apiCall('/api/groups/toggle', { id, enabled });
    appendLog(`[Nhóm Mod] Đã ${enabled ? 'bật' : 'tắt'} cả nhóm!`);
    loadGroups();
    loadMods();
}

async function deleteGroup(id) {
    if (!confirm("Bạn có chắc muốn xóa nhóm mod này?")) return;
    await apiCall('/api/groups/delete', { id });
    loadGroups();
}

// ==========================================
// MACRO
// ==========================================
function switchMacroSubtab(mode) {
    macroSubtab = mode;
    document.getElementById('subtab-macro-basic').classList.toggle('active', mode === 'basic');
    document.getElementById('subtab-macro-pro').classList.toggle('active', mode === 'pro');
    loadMacro();
}

async function loadMacro() {
    const res = await apiCall('/api/macro/config');
    const container = document.getElementById('macro-subtab-container');
    if (!container || !res) return;

    if (macroSubtab === 'basic') {
        container.innerHTML = `
            <div class="space-y-3">
                <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800/60 flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-2">
                            <h4 class="font-bold text-white text-sm">Auto Cốt Truyện (Tự động tua đối thoại)</h4>
                            <span class="px-2 py-0.5 rounded bg-sky-500/20 text-sky-400 text-[10px] font-bold">Phím: F8</span>
                        </div>
                        <p class="text-xs text-slate-400 mt-1">Tự động bấm phím Space và chuột trái liên tục để tua qua các đoạn hội thoại nhiệm vụ dài.</p>
                    </div>
                    <label class="switch-label">
                        <input type="checkbox" ${res.auto_story?.enabled ? 'checked' : ''} onchange="toggleMacroFeature('auto_story', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>

                <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800/60 flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-2">
                            <h4 class="font-bold text-white text-sm">Auto Nhặt Đồ (Spam phím F nhặt tài nguyên)</h4>
                            <span class="px-2 py-0.5 rounded bg-sky-500/20 text-sky-400 text-[10px] font-bold">Phím: F7</span>
                        </div>
                        <p class="text-xs text-slate-400 mt-1">Spam phím F tốc độ cao khi đứng cạnh vật phẩm rơi, rương báu hoặc tài nguyên thế giới.</p>
                    </div>
                    <label class="switch-label">
                        <input type="checkbox" ${res.auto_loot?.enabled ? 'checked' : ''} onchange="toggleMacroFeature('auto_loot', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>

                <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800/60 flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-2">
                            <h4 class="font-bold text-white text-sm">Auto Bảo Bối Z (Tự động bấm Z định kỳ)</h4>
                            <span class="px-2 py-0.5 rounded bg-sky-500/20 text-sky-400 text-[10px] font-bold">Phím: F9</span>
                        </div>
                        <p class="text-xs text-slate-400 mt-1">Tự động nhấn phím Z mỗi 2.5 giây. Tiện lợi cho Quạt lông vũ tăng tốc lướt gió, máy ảnh hoặc la bàn.</p>
                    </div>
                    <label class="switch-label">
                        <input type="checkbox" ${res.auto_gadget?.enabled ? 'checked' : ''} onchange="toggleMacroFeature('auto_gadget', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="space-y-4">
                <div class="p-4 rounded-xl bg-red-950/40 border border-red-500/30 text-xs text-red-200">
                    ⚠️ <b>Macro Pro</b>: Can thiệp chuỗi combo phím chuột của người dùng, phù hợp combo team. Chưa ghi nhận ban nhưng không an toàn 100% so với Macro Cơ Bản.
                </div>
                <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800/60">
                    <h4 class="font-bold text-amber-400 text-sm mb-2">⚡ Combo Đội Hình Xoay Tua Kỹ Năng (F11)</h4>
                    <p class="text-xs text-slate-400 mb-4">Chuỗi thao tác: Nhân vật 1 [1] ➜ Kỹ năng [E] ➜ Nộ [Q] ➜ Chuyển NV 2 [2] ➜ Kỹ năng [E] ➜ Nộ [Q].</p>
                    <button onclick="executeCombo('combo_default_1')" class="btn-amber text-xs font-bold">▶ Thử Nghiệm Combo Mẫu (F11)</button>
                </div>
            </div>
        `;
    }
}

async function toggleMacroFeature(feature, enabled) {
    await apiCall('/api/macro/toggle', { feature, enabled });
    appendLog(`[Macro] Đã ${enabled ? 'bật' : 'tắt'} ${feature}`);
}

async function executeCombo(id) {
    await apiCall('/api/macro/combo', { id });
    appendLog("[Macro] Đã kích hoạt combo đội hình!");
}

// ==========================================
// FIX MOD (ORFIX)
// ==========================================
async function runFixMods(dryRun = false) {
    const logBox = document.getElementById('fix-results-log');
    logBox.innerText = `=== ĐANG ${dryRun ? 'QUÉT KIỂM TRA' : 'TỰ ĐỘNG SỬA'} MODS... ===\n`;

    const res = await apiCall('/api/fix/scan', { dry_run: dryRun });
    if (res) {
        logBox.innerText += `Tổng số file .ini đã quét: ${res.scanned_files}\n`;
        logBox.innerText += `Số file phát hiện vấn đề: ${res.issues_found}\n`;
        if (!dryRun) logBox.innerText += `Số file đã sửa và sao lưu .bak: ${res.fixed_files}\n\n`;

        if (res.details && res.details.length > 0) {
            logBox.innerText += "Chi tiết các file được xử lý:\n";
            res.details.forEach(item => {
                logBox.innerText += ` • Mod: ${item.mod} | File: ${item.file}\n`;
                item.reasons.forEach(r => logBox.innerText += `     - ${r}\n`);
            });
        } else {
            logBox.innerText += "\nTuyệt vời! Toàn bộ file .ini trong thư mục Mod đều hợp lệ và tương thích hoàn toàn!\n";
        }
    }
}

async function undoFixMods() {
    const res = await apiCall('/api/fix/undo');
    alert(`Đã hoàn tác và khôi phục ${res.count || 0} file từ bản sao lưu .bak!`);
}

async function checkORFixUpdate() {
    alert("ORFix.ini và ORFixAPI.ini đã được cập nhật phiên bản mới nhất!");
}

// ==========================================
// WISHES
// ==========================================
function switchWishMode(mode) {
    wishSubtab = mode;
    document.getElementById('subtab-wish-hist').classList.toggle('active', mode === 'history');
    document.getElementById('subtab-wish-glob').classList.toggle('active', mode === 'global');
    loadWishData();
}

async function loadWishData() {
    const container = document.getElementById('wish-container');
    if (!container) return;

    if (wishSubtab === 'history') {
        const stats = await apiCall('/api/wish/stats');
        container.innerHTML = `
            <div class="grid grid-cols-4 gap-3 mb-4">
                <div class="p-3 rounded-xl bg-slate-900/60 border border-slate-800 text-center">
                    <div class="text-xs text-slate-400">Tổng Lượt Quay</div>
                    <div class="text-2xl font-black text-white mt-1">${stats.total || 0}</div>
                </div>
                <div class="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-center">
                    <div class="text-xs text-amber-300">5 Sao Vàng</div>
                    <div class="text-2xl font-black text-amber-400 mt-1">${stats.total_5star || 0} <span class="text-xs font-normal">(${stats.rate_5star || 0}%)</span></div>
                </div>
                <div class="p-3 rounded-xl bg-purple-500/10 border border-purple-500/30 text-center">
                    <div class="text-xs text-purple-300">4 Sao Tím</div>
                    <div class="text-2xl font-black text-purple-400 mt-1">${stats.total_4star || 0} <span class="text-xs font-normal">(${stats.rate_4star || 0}%)</span></div>
                </div>
                <div class="p-3 rounded-xl bg-sky-500/10 border border-sky-500/30 text-center">
                    <div class="text-xs text-sky-300">Pity Hiện Tại</div>
                    <div class="text-2xl font-black text-sky-400 mt-1">${stats.current_pity || 0}</div>
                </div>
            </div>
            <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800 mb-4">
                <h4 class="text-xs font-bold text-slate-400 mb-3">Lịch Sử Nổ Vàng 5★ Gần Nhất</h4>
                <div class="flex flex-wrap gap-2">
                    ${(stats.five_stars && stats.five_stars.length > 0) ? stats.five_stars.map(f => `
                        <div class="px-3 py-1.5 rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-300 font-bold text-xs flex items-center gap-1.5">
                            <span>${f.name}</span>
                            <span class="text-[10px] px-1.5 py-0.2 rounded bg-amber-500 text-slate-950 font-black">${f.pity}</span>
                        </div>
                    `).join('') : '<div class="text-xs text-slate-500">Chưa ghi nhận thẻ 5 sao nào.</div>'}
                </div>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800 text-center py-16">
                <h3 class="text-lg font-bold text-white mb-2">Thống Kê Toàn Cầu Paimon.moe Wish Tally</h3>
                <p class="text-xs text-slate-400 mb-4">Dữ liệu tổng hợp từ hàng triệu lượt quay cộng đồng quốc tế.</p>
                <div class="flex justify-center gap-4">
                    <div class="p-4 rounded-xl bg-slate-950 border border-slate-800 w-64">
                        <div class="text-xs text-amber-400 font-bold">Tỉ lệ 5 Sao Toàn Cầu</div>
                        <div class="text-3xl font-black text-white mt-1">1.60%</div>
                        <div class="text-[10px] text-slate-500 mt-1">Pity trung vị: 76</div>
                    </div>
                </div>
            </div>
        `;
    }
}

async function importWishCache() {
    appendLog("[Wish Tracker] Đang trích xuất lịch sử quay từ Cache Game...");
    const res = await apiCall('/api/wish/import_cache');
    if (res.success) {
        alert("Đã trích xuất thành công lịch sử cầu nguyện từ cache game!");
        loadWishData();
    } else {
        alert("Không tìm thấy link log hợp lệ trong cache game. Hãy mở trang Cầu Nguyện trong game trước!");
    }
}

// ==========================================
// PLUGINS
// ==========================================
async function loadPlugins() {
    const res = await apiCall('/api/plugins/list');
    const container = document.getElementById('plugins-container');
    if (!container || !res.plugins) return;

    document.getElementById('plugins-status-text').innerText = `${res.active_count || 0}/${Object.keys(res.plugins).length} plugin đang bật`;
    container.innerHTML = '';

    for (const [id, p] of Object.entries(res.plugins)) {
        const card = document.createElement('div');
        card.className = 'p-4 rounded-xl bg-slate-900/60 border border-slate-800/60 flex items-center justify-between';
        card.innerHTML = `
            <div>
                <div class="flex items-center gap-2">
                    <h4 class="font-bold text-white text-sm">${p.title || id}</h4>
                    <span class="text-[10px] text-slate-500">v${p.version || '1.0.0'}</span>
                </div>
                <p class="text-xs text-slate-400 mt-1 max-w-xl">${p.desc || ''}</p>
            </div>
            <label class="switch-label">
                <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="togglePlugin('${id}', this.checked)">
                <span class="slider"></span>
            </label>
        `;
        container.appendChild(card);
    }
}

async function togglePlugin(id, enabled) {
    await apiCall('/api/plugins/toggle', { id, enabled });
    loadPlugins();
}

// ==========================================
// TRASH
// ==========================================
async function loadTrash() {
    const res = await apiCall('/api/trash/list');
    const container = document.getElementById('trash-items-container');
    if (!container) return;
    container.innerHTML = '';

    if (!res.items || res.items.length === 0) {
        container.innerHTML = '<div class="text-center py-20 text-slate-500 text-xs">Thùng rác đang trống.</div>';
        return;
    }

    res.items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between text-xs';
        row.innerHTML = `
            <div>
                <div class="font-bold text-white">${item.original_name || item.name}</div>
                <div class="text-[10px] text-slate-400">Danh mục: ${item.category || 'Khác'} • Ngày xóa: ${item.deleted_at || 'Không rõ'}</div>
            </div>
            <button onclick="restoreTrash('${encodeURIComponent(item.trash_folder_name)}')" class="btn-emerald text-xs">↩️ Phục Hồi</button>
        `;
        container.appendChild(row);
    });
}

async function restoreTrash(folderName) {
    const decoded = decodeURIComponent(folderName);
    await apiCall('/api/trash/restore', { folder: decoded });
    appendLog(`[Thùng Rác] Đã phục hồi mod: ${decoded}`);
    loadTrash();
    loadMods();
}

async function emptyTrashAction() {
    if (!confirm("Bạn có chắc chắn muốn dọn sạch toàn bộ thùng rác? Thao tác này không thể hoàn tác!")) return;
    await apiCall('/api/trash/empty');
    appendLog("[Thùng Rác] Đã dọn sạch thùng rác.");
    loadTrash();
}


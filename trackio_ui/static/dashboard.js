
let dashboardData = null;
const chartInstances = new Map();
const chartRegistry = new Map();
const visibleChartIds = new Set();
let enlargedChartInstance = null; // Holds the ECharts instance for the modal

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        const wrapper = entry.target;
        const id = wrapper.id;
        if (entry.isIntersecting) {
            visibleChartIds.add(id);
            const config = chartRegistry.get(id);
            if (config && config.isDirty) {
                renderChart(id, config.metricPath);
            } else {
                const chart = chartInstances.get(id);
                if (chart) chart.resize();
            }
        } else {
            visibleChartIds.delete(id);
        }
    });
}, { root: document.getElementById('charts-container'), rootMargin: '100px' });


// --- 2. Data Handling ---
function updateDashboard(evt) {
    const req = evt.detail?.xhr?.responseURL;
    if (!req || !req.includes('/data') || evt.detail.xhr.status !== 200) return;

    try {
        dashboardData = JSON.parse(evt.detail.xhr.responseText).data;
    } catch (e) { return; }

    const container = document.getElementById('charts-container');
    container.querySelector('.loading-container')?.remove();

    const allMetrics = new Set(Object.values(dashboardData).flatMap(run => Object.keys(run)));
    renderTreeStructure(container, Array.from(allMetrics));
    chartRegistry.forEach(config => config.isDirty = true);
    flushVisibleUpdates();
}

function flushVisibleUpdates() {
    visibleChartIds.forEach(id => {
        const config = chartRegistry.get(id);
        if (config?.isDirty) renderChart(id, config.metricPath);
    });
}

// --- 3. DOM Construction ---

function renderTreeStructure(container, metrics) {
    const rootFolder = getOrCreateFolder(container, "Charts", "root-level-charts", true);
    metrics.sort().forEach(path => {
        const parts = path.split('/');
        let currentParent = parts.length === 1 ? rootFolder : container;
        let displayName = parts[0];
        if (parts.length > 1) {
            let prefix = "folder";
            const maxDepth = Math.min(parts.length - 1, 3);
            for (let i = 0; i < maxDepth; i++) {
                prefix += "-" + parts[i].replace(/[^a-zA-Z0-9]/g, '');
                currentParent = getOrCreateFolder(currentParent, parts[i], prefix, false);
            }
            displayName = parts.slice(maxDepth).join('/');
        }
        const chartId = `chart-${path.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const grid = getOrCreateGrid(currentParent);
        ensureChartContainer(grid, displayName, path, chartId);
        if (!chartRegistry.has(chartId)) {
            chartRegistry.set(chartId, { metricPath: path, isDirty: true });
        }
    });
}

function ensureChartContainer(grid, name, fullPath, chartId) {
    if (document.getElementById(chartId)) return;

    const wrapper = document.createElement('div');
    wrapper.id = chartId;
    wrapper.className = 'card bg-card border shadow-sm h-72 w-full min-w-0 relative group';
    wrapper.style.contain = "strict";
    wrapper.innerHTML = `
        <div class="card-body p-3 h-full flex flex-col">
            <h4 class="text-[10px] font-bold uppercase tracking-wider opacity-40 truncate" title="${fullPath}">${name}</h4>
            <div class="chart-canvas flex-1 w-full min-h-0"></div>
        </div>
        <button onclick="openEnlargeModal('${chartId}')" class="absolute top-1 right-1 btn btn-xs btn-ghost opacity-0 group-hover:opacity-100 transition-opacity">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
        </button>
    `;
    grid.appendChild(wrapper);
    observer.observe(wrapper);
}

// --- 4. Chart Rendering ---

function getLogAxisState() {
    return {
        logX: document.getElementById('log-x-axis')?.checked,
        logY: document.getElementById('log-y-axis')?.checked
    };
}

function renderChart(chartId, metricPath, targetCanvas, optionsOverrides = {}) {
    if (!dashboardData) return;
    const canvas = targetCanvas || document.getElementById(chartId)?.querySelector('.chart-canvas');
    if (!canvas) return;

    let chart = targetCanvas ? null : chartInstances.get(chartId);
    if (!chart) {
        chart = echarts.init(canvas, null, { renderer: 'canvas' });
        if (!targetCanvas) chartInstances.set(chartId, chart);
    }

    const series = Object.entries(dashboardData).map(([runName, metrics]) => {
        const rawData = metrics[metricPath];

        if (!rawData || !rawData.x || !rawData.x.length) return null;

        const plotData = [];
        const x = rawData.x;
        const y = rawData.y;
        const len = x.length;

        for (let i = 0; i < len; i++) {
            plotData.push([x[i], y[i]]);
        }

        return {
            name: runName,
            type: 'line',
            data: plotData,
            showSymbol: false,
            sampling: 'lttb',
            large: true,
            smooth: false,
            animation: false,
            lineStyle: { width: 1.5 }
        };
    }).filter(Boolean);

    const { logX, logY } = getLogAxisState();
    const baseOptions = {
        animation: false,
        tooltip: {
            trigger: 'axis',
            confine: true,
            axisPointer: { type: 'line', snap: true, animation: false },
            formatter: (p) => p.length ? `<div class="p-1"><div class="text-[10px] font-bold mb-1">${p[0].axisValueLabel}</div>${p.map(i => i.value?.[1] != null ? `<div class="flex items-center gap-2">${i.marker} <span class="opacity-70">${i.seriesName}:</span> <span class="font-mono">${i.value[1].toFixed(4)}</span></div>` : '').join('')}</div>` : ''
        },
        grid: { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
        xAxis: { type: logX ? 'log' : 'value', scale: true },
        yAxis: { type: logY ? 'log' : 'value', scale: true, splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } } },
        series: series,
        legend: { bottom: 0, icon: 'circle', type: 'scroll', textStyle: { fontSize: 9 } }
    };

    chart.setOption({ ...baseOptions, ...optionsOverrides }, { notMerge: true });
    if (!targetCanvas) {
        const config = chartRegistry.get(chartId);
        if (config) config.isDirty = false;
    }
    return chart;
}

// --- 5. Modal Logic ---

function createEnlargeModal() {
    if (document.getElementById('chart-modal')) return;
    const modal = document.createElement('div');
    modal.id = 'chart-modal';
    modal.className = 'chart-modal-backdrop';
    modal.innerHTML = `
        <div class="chart-modal-content">
            <div class="flex items-center justify-between mb-2">
                <h3 id="modal-chart-title" class="font-bold text-lg"></h3>
                <button onclick="closeEnlargeModal()" class="btn btn-sm btn-ghost">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
            </div>
            <div id="modal-chart-container" class="modal-chart-container"></div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeEnlargeModal();
    });
}

function openEnlargeModal(chartId) {
    const config = chartRegistry.get(chartId);
    if (!config) return;

    const modal = document.getElementById('chart-modal');
    const titleEl = document.getElementById('modal-chart-title');
    const container = document.getElementById('modal-chart-container');

    titleEl.textContent = config.metricPath;
    modal.classList.add('is-visible');

    // Render a new chart with zooming enabled
    enlargedChartInstance = renderChart(chartId, config.metricPath, container, {
        dataZoom: [{ type: 'inside' }, { type: 'slider' }],
        grid: { bottom: '20%' } // Make more space for slider
    });
}

function closeEnlargeModal() {
    const modal = document.getElementById('chart-modal');
    modal.classList.remove('is-visible');

    // IMPORTANT: Dispose of the chart instance to free memory
    if (enlargedChartInstance) {
        enlargedChartInstance.dispose();
        enlargedChartInstance = null;
    }
}

// --- 6. UI Controls & Event Listeners ---
function updateChartsAxisType() {
    chartRegistry.forEach(c => c.isDirty = true);
    flushVisibleUpdates();
}

let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        visibleChartIds.forEach(id => chartInstances.get(id)?.resize());
        enlargedChartInstance?.resize();
    }, 150);
});

function toggleSidebar() {
    const wrapper = document.getElementById('layout-wrapper');
    const isHidden = wrapper.classList.toggle('sidebar-hidden');
    document.getElementById('sidebar-toggle').innerHTML = isHidden ? `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>` : `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`;
    if (!isHidden && window.splitInstance) window.splitInstance.setSizes(window.splitInstance.getSizes());
    setTimeout(() => visibleChartIds.forEach(id => chartInstances.get(id)?.resize()), 320);
}

// --- Initializer ---
document.addEventListener('DOMContentLoaded', createEnlargeModal);

// --- Helpers ---
function getOrCreateFolder(c, n, i, t) { let e = document.getElementById(i); return e || (e = document.createElement("div"), e.id = i, e.className = "collapse collapse-arrow bg-base-100 border border-base-200 rounded-box w-full shrink-0 mb-2", e.innerHTML = `<input type="checkbox" checked /><div class="collapse-title text-sm font-bold uppercase opacity-60">${n}</div><div class="collapse-content flex flex-col gap-4"></div>`, t ? c.prepend(e) : c.appendChild(e)), e.querySelector(".collapse-content") }
function getOrCreateGrid(c) { let e = c.querySelector(":scope > .charts-grid"); return e || (e = document.createElement("div"), e.className = "charts-grid grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4 w-full mb-4 mt-2", c.prepend(e)), e }
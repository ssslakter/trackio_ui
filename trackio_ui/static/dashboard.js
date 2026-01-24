/**
 * Lazy-Load Dashboard for Trackio
 * Solves "Unresponsive" issues by strictly processing only visible charts.
 */

// --- Global State ---
let dashboardData = null;       // Stores the raw data from server
const chartInstances = new Map(); // DOM ID -> ECharts Instance
const chartRegistry = new Map();  // DOM ID -> { metricPath: string, isDirty: boolean }
const visibleChartIds = new Set(); // IDs of charts currently in viewport

// --- 1. Intersection Observer (The Engine) ---
// This watches which charts are on screen. 
// It automatically triggers an update when you scroll to a dirty chart.
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        // We observe the wrapper div (card)
        const wrapper = entry.target;
        const id = wrapper.id;

        if (entry.isIntersecting) {
            visibleChartIds.add(id);
            // If the chart is outdated (dirty) or empty, render it now.
            const config = chartRegistry.get(id);
            if (config && config.isDirty) {
                renderChart(id, config.metricPath);
            } else {
                // Just a resize check (in case sidebar moved)
                const chart = chartInstances.get(id);
                if (chart) chart.resize();
            }
        } else {
            visibleChartIds.delete(id);
        }
    });
}, { 
    root: document.getElementById('charts-container'), // vital for correct scroll detection
    rootMargin: '100px' // Pre-render charts 100px before they appear
});

// --- 2. Data Handling (The "Lazy" Logic) ---

function updateDashboard(evt) {
    const req = evt.detail && evt.detail.xhr && evt.detail.xhr.responseURL;
    if (!req || !req.includes('/data')) return;
    if (evt.detail.xhr.status !== 200) return;

    let json;
    try { json = JSON.parse(evt.detail.xhr.responseText); } catch (e) { return; }
    
    // 1. Store Data Globally
    dashboardData = json.data;
    
    // 2. Remove spinner
    const container = document.getElementById('charts-container');
    const loader = container.querySelector('.loading-container');
    if (loader) loader.remove();

    // 3. Extract Metrics
    const allMetrics = new Set();
    Object.values(dashboardData).forEach(runData => {
        Object.keys(runData).forEach(key => {
            if (key !== 'step' && key !== 'index') allMetrics.add(key);
        });
    });

    // 4. Build DOM (Fast, does not touch ECharts)
    renderTreeStructure(container, Array.from(allMetrics));

    // 5. Mark ALL charts as dirty (needing update)
    chartRegistry.forEach(config => config.isDirty = true);

    // 6. Update ONLY the visible charts immediately
    flushVisibleUpdates();
}

function flushVisibleUpdates() {
    visibleChartIds.forEach(id => {
        const config = chartRegistry.get(id);
        if (config && config.isDirty) {
            renderChart(id, config.metricPath);
        }
    });
}

// --- 3. DOM Construction (Lightweight) ---

function renderTreeStructure(container, metrics) {
    const rootFolder = getOrCreateFolder(container, "Charts", "root-level-charts", true);
    
    metrics.sort().forEach(path => {
        const parts = path.split('/');
        const isTopLevel = parts.length === 1;
        let currentParent = isTopLevel ? rootFolder : container;
        let displayName = parts[0];

        if (!isTopLevel) {
            let currentPathPrefix = "folder";
            const maxDepth = Math.min(parts.length - 1, 3);
            for (let i = 0; i < maxDepth; i++) {
                currentPathPrefix += "-" + parts[i].replace(/[^a-zA-Z0-9]/g, '');
                currentParent = getOrCreateFolder(currentParent, parts[i], currentPathPrefix, false);
            }
            displayName = parts.slice(maxDepth).join('/');
        }

        const chartId = `chart-${path.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const grid = getOrCreateGrid(currentParent);
        
        // This creates the DIV but does NOT init ECharts yet
        ensureChartContainer(grid, displayName, path, chartId);
        
        // Register the chart so we know what data it needs later
        if (!chartRegistry.has(chartId)) {
            chartRegistry.set(chartId, { metricPath: path, isDirty: true });
        }
    });
}

function ensureChartContainer(grid, name, fullPath, chartId) {
    if (document.getElementById(chartId)) return;

    const wrapper = document.createElement('div');
    wrapper.id = chartId;
    // CSS Optimization: 'contain: strict' tells browser this box is independent
    // This massively speeds up layout when dragging the sidebar.
    wrapper.className = 'card bg-card border shadow-sm h-72 w-full min-w-0';
    wrapper.style.contain = "strict"; 
    wrapper.innerHTML = `
        <div class="card-body p-3 h-full flex flex-col">
            <h4 class="text-[10px] font-bold uppercase tracking-wider opacity-40 truncate" title="${fullPath}">${name}</h4>
            <div class="chart-canvas flex-1 w-full min-h-0"></div>
        </div>
    `;
    grid.appendChild(wrapper);
    observer.observe(wrapper); // Start watching visibility
}

// --- 4. Chart Rendering (The Heavy Lift) ---

function getLogAxisState() {
    return {
        logX: document.getElementById('log-x-axis')?.checked,
        logY: document.getElementById('log-y-axis')?.checked
    };
}

function renderChart(chartId, metricPath) {
    if (!dashboardData) return;

    const wrapper = document.getElementById(chartId);
    if (!wrapper) return;
    const canvasDiv = wrapper.querySelector('.chart-canvas');

    // Init ECharts only when actually needed
    let myChart = chartInstances.get(chartId);
    if (!myChart) {
        myChart = echarts.init(canvasDiv, null, { renderer: 'canvas' });
        chartInstances.set(chartId, myChart);
    }

    // Build Series
    const series = [];
    Object.entries(dashboardData).forEach(([runName, runMetrics]) => {
        const plotData = runMetrics[metricPath];
        if (plotData && plotData.length > 0) {
            series.push({
                name: runName,
                type: 'line',
                data: plotData,     
                showSymbol: false,
                sampling: 'lttb', // Essential for performance
                large: true,      // Essential for performance
                smooth: false,
                animation: false, // Essential: Animation kills CPU on large datasets
                lineStyle: { width: 1.5 }
            });
        }
    });

    const { logX, logY } = getLogAxisState();
    
    myChart.setOption({
        animation: false,
        tooltip: {
            trigger: 'axis',
            confine: true,
            axisPointer: { type: 'line', snap: true, animation: false },
            formatter: (params) => {
                if(!params.length) return '';
                let res = `<div class="text-[10px] font-bold mb-1">${params[0].axisValueLabel}</div>`;
                params.forEach(item => {
                    if (item.value?.[1] != null) {
                        res += `<div class="flex items-center gap-2">${item.marker} <span class="opacity-70">${item.seriesName}:</span> <span class="font-mono">${item.value[1].toFixed(4)}</span></div>`;
                    }
                });
                return `<div class="p-1">${res}</div>`;
            }
        },
        grid: { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
        xAxis: { type: logX ? 'log' : 'value', scale: true },
        yAxis: { type: logY ? 'log' : 'value', scale: true, splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } } },
        series: series,
        legend: { bottom: 0, icon: 'circle', type: 'scroll', textStyle: { fontSize: 9 } }
    }, { notMerge: true }); // notMerge=true ensures clean state

    // Mark as clean
    const config = chartRegistry.get(chartId);
    if (config) config.isDirty = false;
}

// --- 5. UI Controls & Event Listeners ---

// Optimized Toggle: Only updates visible charts
function updateChartsAxisType() {
    // 1. Mark ALL as dirty so they update when scrolled to
    chartRegistry.forEach(c => c.isDirty = true);
    // 2. Update visible ones immediately
    flushVisibleUpdates();
}

// Optimized Resize: Debounce to prevent lag during drag
let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        visibleChartIds.forEach(id => {
            const chart = chartInstances.get(id);
            if (chart) chart.resize();
        });
    }, 150);
});

function toggleSidebar() {
    const wrapper = document.getElementById('layout-wrapper');
    const isHidden = wrapper.classList.toggle('sidebar-hidden');
    
    // Update Toggle Icon
    document.getElementById('sidebar-toggle').innerHTML = isHidden ? 
        `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>` :
        `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`;

    // If Split.js is active, tell it to recalc
    if (!isHidden && window.splitInstance) {
        window.splitInstance.setSizes(window.splitInstance.getSizes());
    }

    // Delay resize until transition ends (300ms)
    setTimeout(() => {
        visibleChartIds.forEach(id => {
            const chart = chartInstances.get(id);
            if (chart) chart.resize();
        });
    }, 320);
}

// --- Helpers ---
function getOrCreateFolder(container, name, id, forceTop) {
    let folder = document.getElementById(id);
    if (!folder) {
        folder = document.createElement('div');
        folder.id = id;
        folder.className = 'collapse collapse-arrow bg-base-100 border border-base-200 rounded-box w-full shrink-0 mb-2';
        folder.innerHTML = `<input type="checkbox" checked /><div class="collapse-title text-sm font-bold uppercase opacity-60">${name}</div><div class="collapse-content flex flex-col gap-4"></div>`;
        forceTop ? container.prepend(folder) : container.appendChild(folder);
    }
    return folder.querySelector('.collapse-content');
}

function getOrCreateGrid(container) {
    let grid = container.querySelector(':scope > .charts-grid');
    if (!grid) {
        grid = document.createElement('div');
        grid.className = 'charts-grid grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4 w-full mb-4 mt-2';
        container.prepend(grid);
    }
    return grid;
}
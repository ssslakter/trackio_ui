const chartInstances = new Map();

function toggleSidebar() {
    const wrapper = document.getElementById('layout-wrapper');
    const btn = document.getElementById('sidebar-toggle');
    const isHidden = wrapper.classList.toggle('sidebar-hidden');

    btn.innerHTML = isHidden ?
        `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>` :
        `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>`;

    if (!isHidden && window.splitInstance) {
        window.splitInstance.setSizes(window.splitInstance.getSizes());
    }

    setTimeout(() => {
        chartInstances.forEach(chart => chart.resize());
    }, 310);
}


function updateDashboard(evt) {
    if (evt.detail.xhr.status !== 200) return;
    const data = JSON.parse(evt.detail.xhr.responseText).data;
    const container = document.getElementById('charts-container');
    if (!container) return;

    const loader = container.querySelector('.loading-container');
    if (loader) loader.remove();

    const allMetrics = new Set();
    Object.values(data).forEach(runData => {
        Object.keys(runData).forEach(key => {
            if (key !== 'step' && key !== 'index') allMetrics.add(key);
        });
    });

    renderTree(container, Array.from(allMetrics), data);
}

function renderTree(container, metrics, data) {
    const rootFolder = getOrCreateFolder(container, "Charts", "root-level-charts", true);
    const sortedMetrics = metrics.sort();

    sortedMetrics.forEach(path => {
        const parts = path.split('/');
        const isTopLevel = parts.length === 1;

        let currentParent;
        let displayName;

        if (isTopLevel) {
            currentParent = rootFolder;
            displayName = parts[0];
        } else {
            let folderParent = container;
            let currentPathPrefix = "folder";
            const maxDepth = Math.min(parts.length - 1, 3);

            for (let i = 0; i < maxDepth; i++) {
                currentPathPrefix += "-" + parts[i].replace(/[^a-zA-Z0-9]/g, '');
                folderParent = getOrCreateFolder(folderParent, parts[i], currentPathPrefix, false);
            }
            currentParent = folderParent;
            displayName = parts.slice(maxDepth).join('/');
        }

        const chartId = `chart-${path.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const grid = getOrCreateGrid(currentParent);
        const chartCanvas = getOrCreateChartElement(grid, displayName, path, chartId);
        updateChartInstance(chartId, chartCanvas, path, data);
    });
}

function getOrCreateFolder(container, name, id, forceTop) {
    let folder = document.getElementById(id);
    if (!folder) {
        folder = document.createElement('div');
        folder.id = id;
        folder.className = 'collapse collapse-arrow bg-base-100 border border-base-200 rounded-box w-full shrink-0';
        folder.innerHTML = `
            <input type="checkbox" checked /> 
            <div class="collapse-title text-sm font-bold uppercase opacity-60">${name}</div>
            <div class="collapse-content flex flex-col gap-4"></div>
        `;
        // Put "Charts" root folder at the very top, others at bottom
        if (forceTop) container.prepend(folder);
        else container.appendChild(folder);
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

function checkIsSparse(values) {
    if (!values || values.length === 0) return false;

    const totalPoints = values.length;
    const validPoints = values.filter(v => v !== null && v !== undefined).length;
    const nullRatio = (totalPoints - validPoints) / totalPoints;

    return nullRatio > 0.9;
}


function getOrCreateChartElement(grid, name, fullPath, chartId) {
    let wrapper = document.getElementById(chartId);
    if (!wrapper) {
        wrapper = document.createElement('div');
        wrapper.id = chartId;
        wrapper.className = 'card bg-card border shadow-sm h-72 w-full min-w-0';
        wrapper.innerHTML = `
            <div class="card-body p-3 h-full flex flex-col">
                <h4 class="text-[10px] font-bold uppercase tracking-wider opacity-40 truncate" title="${fullPath}">${name}</h4>
                <div class="chart-canvas flex-1 w-full min-h-0"></div>
            </div>
        `;
        grid.appendChild(wrapper);
    }
    return wrapper.querySelector('.chart-canvas');
}

function updateChartInstance(chartId, el, metricPath, data) {
    let myChart = chartInstances.get(chartId);
    if (!myChart) {
        myChart = echarts.init(el);
        chartInstances.set(chartId, myChart);
        new ResizeObserver(() => myChart.resize()).observe(el);
    }

    const series = [];
    Object.entries(data).forEach(([runName, metrics]) => {
        const steps = metrics.step || metrics.index;
        const values = metrics[metricPath];

        if (steps && values) {
            // 1. Filter out nulls so ECharts doesn't "snap" to empty data
            const plotData = steps
                .map((v, i) => [v, values[i]])
                .filter(point => point[1] !== null && point[1] !== undefined);

            // 2. Reuse the sparsity check on the original values 
            // (or plotData if you prefer)
            const isSparse = checkIsSparse(values);

            series.push({
                name: runName,
                type: 'line',
                data: plotData, // Clean data with no nulls
                showSymbol: isSparse,
                symbolSize: 6,
                // Even though we filtered nulls, we use connectNulls 
                // to draw lines between sparse points
                connectNulls: true,
                smooth: true,
                lineStyle: { width: 1.5 }
            });
        }
    });

    myChart.setOption({
        animation: false,
        tooltip: {
            trigger: 'axis',
            confine: true,
            // 3. Improve snapping behavior
            axisPointer: {
                type: 'line', // Vertical line
                snap: true    // Snaps the line to the nearest data point
            },
            // 4. Custom formatter to only show series that actually have data at this step
            formatter: function (params) {
                let res = `<div class="text-[10px] font-bold mb-1">${params[0].axisValueLabel}</div>`;
                params.forEach(item => {
                    // Only show items that aren't null (extra safety)
                    if (item.value[1] !== null && item.value[1] !== undefined) {
                        res += `<div class="flex items-center gap-2">
                            ${item.marker} 
                            <span class="opacity-70">${item.seriesName}:</span> 
                            <span class="font-mono">${item.value[1].toFixed(4)}</span>
                        </div>`;
                    }
                });
                return `<div class="p-1">${res}</div>`;
            }
        },
        grid: { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
        xAxis: {
            type: 'value',
            scale: true,
            splitLine: { show: false }
        },
        yAxis: {
            type: 'value',
            scale: true,
            splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } }
        },
        series: series,
        legend: { bottom: 0, icon: 'circle', textStyle: { fontSize: 9 }, type: 'scroll' }
    }, { notMerge: true });
}
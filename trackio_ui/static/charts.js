const Charts = (() => {
    // --- State ---
    const instances = new Map();     // path -> ECharts instance
    const dataCache = new Map();     // path -> { runName: {x, y, ts?} }
    const runColors = new Map();

    const visiblePaths = new Set();  // Paths currently in the viewport
    const pendingRenders = new Set(); // Paths that need a setOption update

    // Asynchronous render queue to prevent scroll lag
    const renderQueue = new Set();
    let isProcessingQueue = false;

    const timeAxisPaths = new Set();
    const tsOptionalPaths = new Set();

    let logX = false, logY = false, useTime = false;
    let modalInstance = null;

    // --- Theme & Sizing Helpers ---
    function cssColor(varName, fallback) {
        const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
        return v ? `hsl(${v})` : fallback;
    }

    function themeColors() {
        return {
            text: cssColor('--foreground', '#666'),
            tooltipBg: cssColor('--card', '#fff'),
            tooltipBorder: cssColor('--border', '#e5e7eb'),
        };
    }

    function legendFontSize() {
        return document.documentElement.classList.contains('uk-font-base') ? 12 : 11;
    }

    let currentTheme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    let currentFont = document.documentElement.classList.contains('uk-font-base');

    new MutationObserver(() => {
        const newTheme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        const newFont = document.documentElement.classList.contains('uk-font-base');

        if (newTheme !== currentTheme || newFont !== currentFont) {
            currentTheme = newTheme;
            currentFont = newFont;
            flagAllForRender(); // Theme/font change requires full redraw
        }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    // --- Formatters ---
    function formatDuration(sec) {
        if (sec == null || isNaN(sec)) return '';
        const isNeg = sec < 0;
        sec = Math.abs(sec);
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = sec < 60 ? (sec % 60).toFixed(1) : Math.floor(sec % 60);
        let res = (h > 0) ? `${h}h ${m}m` : (m > 0) ? `${m}m ${Math.floor(sec % 60)}s` : `${s}s`;
        return isNeg ? "-" + res : res;
    }

    function buildTooltip(params, useTimeAxis) {
        if (!params.length) return '';
        const val = params[0].value?.[0];
        const label = (useTimeAxis && val != null) ? formatDuration(val) : params[0].axisValueLabel;
        const rows = params.filter(p => p.value?.[1] != null)
            .map(p => `${p.marker} ${p.seriesName}: <b>${p.value[1].toFixed(4)}</b>`).join('<br>');
        return `<small>${label}</small><br>${rows}`;
    }

    // --- Render Chunking (Fixes Scroll "Teleportation" Lag) ---
    function processQueue() {
        if (renderQueue.size === 0) {
            isProcessingQueue = false;
            return;
        }

        let processed = 0;
        const batchSize = 3; // Number of charts to render per frame (keeps UI at 60fps)

        for (const path of renderQueue) {
            renderQueue.delete(path);

            // Only process if it's STILL in the viewport
            if (visiblePaths.has(path)) {
                // Ensure the width is accurate before we render
                const chart = instances.get(path);
                if (chart) chart.resize();

                if (pendingRenders.has(path) && dataCache.has(path)) {
                    renderChart(path);
                }
            }

            processed++;
            if (processed >= batchSize) break;
        }

        if (renderQueue.size > 0) {
            requestAnimationFrame(processQueue);
        } else {
            isProcessingQueue = false;
        }
    }

    function clearQueue() {
        renderQueue.clear();
        pendingRenders.clear();
        isProcessingQueue = false;
    }

    function queueForRender(path) {
        renderQueue.add(path);
        if (!isProcessingQueue) {
            isProcessingQueue = true;
            requestAnimationFrame(processQueue);
        }
    }

    // --- Visibility Observer ---
    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            const path = entry.target.dataset.metric;
            if (entry.isIntersecting) {
                visiblePaths.add(path);
                queueForRender(path);
            } else {
                visiblePaths.delete(path);
                // If user scrolls past quickly, cancel the queued render to save CPU
                renderQueue.delete(path);
            }
        });
    }, { rootMargin: '300px' });

    function observeAll() {
        document.querySelectorAll('[data-metric]').forEach(el => observer.observe(el));
    }

    // --- Core Rendering Logic ---
    function renderChart(path) {
        const cardEl = document.querySelector(`[data-metric="${path}"]`);
        const canvas = cardEl?.querySelector('.chart-canvas');

        // Prevent initialization if the canvas is inside a collapsed accordion folder
        if (!canvas || canvas.clientWidth < 50) {
            pendingRenders.add(path);
            return;
        }

        pendingRenders.delete(path);

        let chart = instances.get(path);
        if (!chart) {
            chart = echarts.init(canvas, null, { renderer: 'canvas' });
            instances.set(path, chart);
        }

        chart.resize();

        const options = buildChartOptions(buildSeries(path), themeColors(), path);
        chart.setOption(options, { notMerge: true });
    }

    function flagAllForRender() {
        for (const path of dataCache.keys()) {
            if (visiblePaths.has(path)) {
                queueForRender(path);
            } else {
                pendingRenders.add(path);
            }
        }
        if (modalInstance) {
            const title = document.getElementById('chart-modal-title')?.textContent;
            if (title && dataCache.has(title)) renderModal(title);
        }
    }

    // --- Fast Resize (Window / Sidebar Drag) ---
    function resizeVisible() {
        for (const path of visiblePaths) {
            const chart = instances.get(path);
            if (chart) chart.resize();

            // If the chart was skipped due to 0-width previously, queue it now
            if (pendingRenders.has(path) && dataCache.has(path)) {
                queueForRender(path);
            }
        }
        if (modalInstance) modalInstance.resize();
    }

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(resizeVisible, 100);
    });

    document.addEventListener('toggle', (e) => {
        if (e.target.tagName === 'DETAILS' && e.target.open) {
            setTimeout(resizeVisible, 50);
        }
    }, true);

    // --- Data Management ---
    function getCurrentSchema() {
        return Array.from(document.querySelectorAll('[data-metric]')).map(el => el.dataset.metric);
    }

    function ingestAxisMetadata(raw) {
        if (raw.time_axis_paths) raw.time_axis_paths.forEach(p => timeAxisPaths.add(p));
        if (raw.ts_optional_paths) raw.ts_optional_paths.forEach(p => tsOptionalPaths.add(p));
    }

    function ingestData(payload, isLive = false) {
        let needsLayoutRefresh = false;
        const existingSchema = new Set(getCurrentSchema());

        for (const [run, metrics] of Object.entries(payload)) {
            for (const [path, series] of Object.entries(metrics)) {
                if (isLive && !existingSchema.has(path)) {
                    needsLayoutRefresh = true;
                }

                if (!dataCache.has(path)) dataCache.set(path, {});
                dataCache.get(path)[run] = series;

                if (visiblePaths.has(path)) {
                    queueForRender(path);
                } else {
                    pendingRenders.add(path);
                }
            }
        }

        if (isLive && needsLayoutRefresh) {
            document.getElementById('main-refresh-btn')?.click();
        } else if (modalInstance) {
            const title = document.getElementById('chart-modal-title')?.textContent;
            if (title && dataCache.has(title)) renderModal(title);
        }
    }

    function pruneRuns(activeRuns) {
        const active = new Set(activeRuns);
        for (const [path, runs] of dataCache.entries()) {
            for (const run of Object.keys(runs)) {
                if (!active.has(run)) delete runs[run];
            }
            if (!Object.keys(runs).length) dataCache.delete(path);
        }
    }

    // --- Chart Building ---
    function colorFor(run) {
        if (!runColors.has(run)) {
            const palette = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc'];
            runColors.set(run, palette[runColors.size % palette.length]);
        }
        return runColors.get(run);
    }

    function isTimeAxis(path) {
        return timeAxisPaths.has(path) || (useTime && tsOptionalPaths.has(path));
    }

    function buildSeries(path) {
        const EPS = 1e-10;
        const useTimeAxis = isTimeAxis(path);

        return Object.entries(dataCache.get(path) ?? {}).map(([run, series]) => {
            const { x, y, ts } = series;

            let xData = x;
            if (useTimeAxis) {
                if (timeAxisPaths.has(path)) xData = x;
                else if (ts) xData = ts;
                else xData = []; // Don't plot step data against a time axis
            }

            const data = xData.map((v, i) => [
                logX ? Math.max(EPS, v) : v,
                logY ? Math.max(EPS, y[i]) : y[i],
            ]);

            return {
                name: run, type: 'line', data,
                showSymbol: false, animation: false,
                lineStyle: { width: 1.5 },
                itemStyle: { color: colorFor(run) },
            };
        });
    }

    function buildChartOptions(series, colors, path = '', extra = {}) {
        const EPS = 1e-10;
        const useTimeAxis = isTimeAxis(path);

        const opts = {
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: (params) => buildTooltip(params, useTimeAxis),
                backgroundColor: colors.tooltipBg,
                borderColor: colors.tooltipBorder,
                textStyle: { color: colors.text, fontSize: 12 },
            },
            grid: extra.grid ?? { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
            xAxis: {
                type: logX ? 'log' : 'value',
                scale: !useTimeAxis,
                min: logX ? EPS : undefined,
                axisLabel: useTimeAxis ? { formatter: formatDuration } : undefined
            },
            yAxis: {
                type: logY ? 'log' : 'value', scale: true, min: logY ? EPS : undefined,
                splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } },
            },
            series,
            legend: {
                bottom: 0, icon: 'circle', type: 'scroll',
                textStyle: { fontSize: legendFontSize(), color: colors.text },
                data: series.map(s => ({ name: s.name, itemStyle: { color: colorFor(s.name) } })),
            },
        };
        if (extra.dataZoom) opts.dataZoom = extra.dataZoom;
        return opts;
    }

    // --- Modal ---
    function renderModal(path) {
        modalInstance.setOption(buildChartOptions(buildSeries(path), themeColors(), path, {
            grid: { left: '8%', right: '4%', top: '8%', bottom: '22%', containLabel: true },
            dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: '8%' }],
        }), { notMerge: true });
    }

    function openModal(path) {
        if (!dataCache.has(path)) return;
        document.getElementById('chart-modal-title').textContent = path;

        if (!modalInstance) {
            const canvas = document.getElementById('chart-modal-canvas');
            const modalW = Math.min(window.innerWidth * 0.85, 1200) - 80;
            modalInstance = echarts.init(canvas, null, { renderer: 'canvas', width: modalW, height: 520 });
        }

        renderModal(path);
        UIkit.modal('#chart-modal').show();

        document.getElementById('chart-modal').addEventListener('shown', () => {
            modalInstance?.resize();
        }, { once: true });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('chart-modal')?.addEventListener('hidden', () => {
            if (modalInstance) {
                modalInstance.dispose();
                modalInstance = null;
            }
        });
    });

    // --- Initialization & HTMX Hooks ---
    document.addEventListener('htmx:afterSettle', (e) => {
        if (e.target?.querySelectorAll) {
            e.target.querySelectorAll('[data-metric]').forEach(el => observer.observe(el));
        }

        const island = document.getElementById('chart-data-payload');
        if (!island || island.dataset.processed) return;
        island.dataset.processed = "true";

        setTimeout(() => {
            const raw = JSON.parse(island.textContent);
            if (!raw.data) return;
            const { data, runs, schema_changed } = raw;

            ingestAxisMetadata(raw);

            if (schema_changed) {
                instances.forEach(c => c.dispose());
                instances.clear();
                runColors.clear();
                visiblePaths.clear();
                pendingRenders.clear();
                renderQueue.clear();
                observer.disconnect();
                observeAll();
            }

            pruneRuns(runs);
            ingestData(data);
        }, 0);
    });

    document.addEventListener('htmx:beforeSwap', e => {
        if (e.detail.target.id === 'main-content') {
            instances.forEach(c => c.dispose());
            instances.clear();
            visiblePaths.clear();
            pendingRenders.clear();
            renderQueue.clear();
            observer.disconnect();
        }
    });

    document.addEventListener('charts:data', e => ingestData(e.detail, false));
    document.addEventListener('charts:live_data', e => {
        ingestAxisMetadata(e.detail);
        ingestData(e.detail.data ?? e.detail, true);
    });

    return {
        observeAll, ingestData, pruneRuns, openModal, getCurrentSchema, clearQueue,
        setAxes: (x, y, t) => { logX = x; logY = y; useTime = t; flagAllForRender(); },
        resize: resizeVisible,
    };
})();

document.addEventListener('DOMContentLoaded', Charts.observeAll);
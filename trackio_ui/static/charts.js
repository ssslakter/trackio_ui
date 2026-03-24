const Charts = (() => {
    const instances = new Map();    // metricPath -> ECharts instance
    const dataCache = new Map();    // metricPath -> { runName: {x, y, ts?} }
    const runColors = new Map();
    const visibleCharts = new Set();   // Keep track of visible charts
    const renderedSchema = new Set();  // tracks what's currently rendered

    // Paths that always use a time x-axis (system/* metrics).
    const timeAxisPaths = new Set();
    // Paths that have optional timestamps alongside steps (normal metrics with "ts").
    const tsOptionalPaths = new Set();

    let logX = false, logY = false;
    let modalInstance = null;

    // --- Theme helpers ---

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
    new MutationObserver(() => {
        const newTheme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        if (newTheme !== currentTheme) {
            currentTheme = newTheme;
            renderVisible();
            if (modalInstance) {
                const path = document.getElementById('chart-modal-title')?.textContent;
                if (path) openModal(path);
            }
        }
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    // --- Observer (lazy render) ---

    const observer = new IntersectionObserver(entries => {
        entries.forEach(({ target, isIntersecting }) => {
            const path = target.dataset.metric;
            if (isIntersecting) {
                visibleCharts.add(path);
                if (dataCache.has(path)) renderChart(target);
            } else {
                visibleCharts.delete(path);
            }
        });
    }, { rootMargin: '120px' });

    function observeAll() {
        document.querySelectorAll('[data-metric]').forEach(el => observer.observe(el));
    }

    // --- Data ---

    function getCurrentSchema() {
        return Array.from(document.querySelectorAll('[data-metric]'))
            .map(el => el.dataset.metric);
    }

    function ingestAxisMetadata(raw) {
        // Register which paths use a forced time axis and which have optional timestamps.
        if (raw.time_axis_paths) {
            for (const p of raw.time_axis_paths) timeAxisPaths.add(p);
        }
        if (raw.ts_optional_paths) {
            for (const p of raw.ts_optional_paths) tsOptionalPaths.add(p);
        }
    }

    function ingestData(payload, isLive = false) {
        let needsLayoutRefresh = false;
        const existingSchema = new Set(getCurrentSchema());

        for (const [run, metrics] of Object.entries(payload)) {
            for (const [path, series] of Object.entries(metrics)) {
                if (isLive && !existingSchema.has(path)) {
                    needsLayoutRefresh = true;
                }

                if (!dataCache.get(path)) dataCache.set(path, {});
                dataCache.get(path)[run] = series;
            }
        }

        if (needsLayoutRefresh) {
            document.getElementById('main-refresh-btn')?.click();
        } else {
            renderVisible();
        }
    }

    function pruneRuns(activeRuns) {
        const active = new Set(activeRuns);
        for (const [path, runs] of dataCache.entries()) {
            for (const run of Object.keys(runs))
                if (!active.has(run)) delete runs[run];
            if (!Object.keys(runs).length) dataCache.delete(path);
        }
    }

    // --- Rendering ---

    function colorFor(run) {
        if (!runColors.has(run)) {
            const palette = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
                '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc'];
            runColors.set(run, palette[runColors.size % palette.length]);
        }
        return runColors.get(run);
    }

    /**
     * Returns true if this path should render its x-axis as wall-clock time.
     * System metrics always use time. Step metrics use time only if they have
     * timestamps AND logX is off (log(time) is not meaningful).
     */
    function isTimeAxis(path) {
        if (timeAxisPaths.has(path)) return true;
        // Future: could let the user toggle tsOptionalPaths via a UI control.
        return false;
    }

    function buildSeries(path) {
        const EPS = 1e-10;
        const useTime = isTimeAxis(path);

        return Object.entries(dataCache.get(path) ?? {}).map(([run, series]) => {
            const { x, y, ts } = series;
            // For time-axis charts use timestamps (ms); for step-axis use steps.
            // ts is present on time-optional step metrics; x is always present.
            const xData = useTime ? (ts ?? x) : x;

            const data = xData.map((v, i) => [
                (!useTime && logX) ? Math.max(EPS, v) : v,
                logY ? Math.max(EPS, y[i]) : y[i],
            ]);

            return {
                name: run, type: 'line',
                data,
                showSymbol: false, animation: false,
                lineStyle: { width: 1.5 },
                itemStyle: { color: colorFor(run) },
            };
        });
    }

    function buildChartOptions(series, colors, path = '', extra = {}) {
        const EPS = 1e-10;
        const useTime = isTimeAxis(path);

        // Time-axis charts never support log-x (log(unix_ms) is meaningless).
        const xAxisType = useTime ? 'time' : (logX ? 'log' : 'value');

        const opts = {
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: useTime ? timeTooltipFormatter : tooltipFormatter,
                backgroundColor: colors.tooltipBg,
                borderColor: colors.tooltipBorder,
                textStyle: { color: colors.text, fontSize: 12 },
            },
            grid: extra.grid ?? { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
            xAxis: {
                type: xAxisType,
                scale: !useTime,
                min: (!useTime && logX) ? EPS : undefined,
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

    function tooltipFormatter(params) {
        if (!params.length) return '';
        const rows = params
            .filter(p => p.value?.[1] != null)
            .map(p => `${p.marker} ${p.seriesName}: <b>${p.value[1].toFixed(4)}</b>`)
            .join('<br>');
        return `<small>${params[0].axisValueLabel}</small><br>${rows}`;
    }

    function timeTooltipFormatter(params) {
        if (!params.length) return '';
        const ts = params[0].value?.[0];
        const label = ts != null ? new Date(ts).toLocaleString() : params[0].axisValueLabel;
        const rows = params
            .filter(p => p.value?.[1] != null)
            .map(p => `${p.marker} ${p.seriesName}: <b>${p.value[1].toFixed(4)}</b>`)
            .join('<br>');
        return `<small>${label}</small><br>${rows}`;
    }

    function renderVisible() {
        document.querySelectorAll('[data-metric]').forEach(el => {
            const path = el.dataset.metric;
            if (visibleCharts.has(path) && dataCache.has(path)) {
                renderChart(el);
            }
        });

        if (modalInstance) {
            const modalTitleEl = document.getElementById('chart-modal-title');
            const path = modalTitleEl ? modalTitleEl.textContent : null;
            if (path && dataCache.has(path)) {
                modalInstance.setOption({
                    series: buildSeries(path)
                });
            }
        }
    }

    function renderChart(cardEl) {
        const path = cardEl.dataset.metric;
        const canvas = cardEl.querySelector('.chart-canvas');
        if (!canvas) return;
        let chart = instances.get(path);
        if (!chart) {
            chart = echarts.init(canvas, null, { renderer: 'canvas' });
            instances.set(path, chart);
        }
        chart.setOption(
            buildChartOptions(buildSeries(path), themeColors(), path),
            { notMerge: true }
        );
    }

    // --- Modal ---

    function openModal(path) {
        if (!dataCache.has(path)) return;
        document.getElementById('chart-modal-title').textContent = path;

        const canvas = document.getElementById('chart-modal-canvas');
        if (!modalInstance) {
            const modalW = Math.min(window.innerWidth * 0.85, 1200) - 80;
            modalInstance = echarts.init(canvas, null, { renderer: 'canvas', width: modalW, height: 520 });
        }

        modalInstance.setOption(
            buildChartOptions(buildSeries(path), themeColors(), path, {
                grid: { left: '8%', right: '4%', top: '8%', bottom: '22%', containLabel: true },
                dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: '8%' }],
            }),
            { notMerge: true }
        );

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

    // --- Settings ---

    function setLogAxes(x, y) {
        logX = x; logY = y;
        renderVisible();
        if (modalInstance) {
            const path = document.getElementById('chart-modal-title')?.textContent;
            if (path) openModal(path);
        }
    }

    // --- Resize ---

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            instances.forEach(c => c.resize());
            modalInstance?.resize();
        }, 150);
    });

    document.addEventListener('htmx:afterSettle', (e) => {
        const targetEl = e.target;
        if (targetEl && targetEl.querySelectorAll) {
            targetEl.querySelectorAll('[data-metric]').forEach(el => observer.observe(el));
        }

        const island = document.getElementById('chart-data-payload');

        if (!island || island.dataset.processed) return;
        island.dataset.processed = "true";

        const raw = JSON.parse(island.textContent);
        if (!raw.data) return;
        const { data, runs, schema_changed } = raw;

        ingestAxisMetadata(raw);

        if (schema_changed) {
            instances.forEach(c => c.dispose());
            instances.clear();
            runColors.clear();
            visibleCharts.clear();
            renderedSchema.clear();
            observer.disconnect();
            observeAll();
        }
        for (const [run, metrics] of Object.entries(data)) {
            for (const path of Object.keys(metrics)) {
                renderedSchema.add(path);
            }
        }
        pruneRuns(runs);
        ingestData(data);
    });

    document.addEventListener('htmx:beforeSwap', e => {
        // Only clear out when the actual content pane swaps
        if (e.detail.target.id === 'main-content') {
            instances.forEach(c => c.dispose());
            instances.clear();
            visibleCharts.clear();
            observer.disconnect();
        }
    });

    document.addEventListener('charts:data', e => ingestData(e.detail, false));
    document.addEventListener('charts:live_data', e => {
        ingestAxisMetadata(e.detail);
        ingestData(e.detail.data ?? e.detail, true);
    });

    return {
        observeAll, ingestData, pruneRuns, setLogAxes, openModal,
        getCurrentSchema,
        resize: () => instances.forEach(c => c.resize()),
    };
})();

document.addEventListener('DOMContentLoaded', Charts.observeAll);
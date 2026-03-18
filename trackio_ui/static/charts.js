const Charts = (() => {
    const instances = new Map();  // metricPath -> ECharts instance
    const dataCache = new Map();  // metricPath -> { runName: {x, y} }
    const runColors = new Map();
    const visibleCharts = new Set(); // Keep track of visible charts

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

    function ingestData(payload) {
        for (const [run, metrics] of Object.entries(payload))
            for (const [path, series] of Object.entries(metrics))
                (dataCache.get(path) ?? dataCache.set(path, {}).get(path))[run] = series;
        renderVisible();
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

    function buildSeries(path) {
        const EPS = 1e-10;
        return Object.entries(dataCache.get(path) ?? {}).map(([run, { x, y }]) => ({
            name: run, type: 'line',
            data: x.map((v, i) => [logX ? Math.max(EPS, v) : v,
            logY ? Math.max(EPS, y[i]) : y[i]]),
            showSymbol: false, animation: false,
            lineStyle: { width: 1.5 },
            itemStyle: { color: colorFor(run) },
        }));
    }

    function buildChartOptions(series, colors, extra = {}) {
        const EPS = 1e-10;
        const opts = {
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: tooltipFormatter,
                backgroundColor: colors.tooltipBg,
                borderColor: colors.tooltipBorder,
                textStyle: { color: colors.text, fontSize: 12 },
            },
            grid: extra.grid ?? { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
            xAxis: { type: logX ? 'log' : 'value', scale: true, min: logX ? EPS : undefined },
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

    function renderVisible() {
        document.querySelectorAll('[data-metric]').forEach(el => {
            const path = el.dataset.metric;
            if (visibleCharts.has(path) && dataCache.has(path)) {
                renderChart(el);
            }
        });
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
            buildChartOptions(buildSeries(path), themeColors()),
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
            buildChartOptions(buildSeries(path), themeColors(), {
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
        if (schema_changed) {
            instances.forEach(c => c.dispose());
            instances.clear();
            runColors.clear();
            visibleCharts.clear();
            observer.disconnect();
            observeAll();
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

    document.addEventListener('charts:data', e => ingestData(e.detail));

    return {
        observeAll, ingestData, pruneRuns, setLogAxes, openModal,
        getCurrentSchema: () => [...instances.keys()],
        resize: () => instances.forEach(c => c.resize()),
    };
})();

document.addEventListener('DOMContentLoaded', Charts.observeAll);

document.addEventListener('htmx:configRequest', e => {
    if (!e.detail.path.includes('/layout')) return;
    Charts.getCurrentSchema().forEach(path =>
        e.detail.parameters.append('current_schema', path)
    );
});
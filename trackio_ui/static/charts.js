const Charts = (() => {
    const instances = new Map();  // metricPath -> ECharts instance
    const dataCache = new Map();  // metricPath -> { runName: {x, y} }
    const runColors = new Map();

    let logX = false, logY = false;
    let modalInstance = null;

    // --- Observer ---

    const observer = new IntersectionObserver(entries => {
        entries.forEach(({ target, isIntersecting }) => {
            if (isIntersecting && dataCache.has(target.dataset.metric))
                renderChart(target);
        });
    }, { rootMargin: '120px' });

    function observeAll() {
        document.querySelectorAll('[data-metric]').forEach(el => observer.observe(el));
    }

    // --- Data ---

    // payload: { runName: { metricPath: { x: [], y: [] } } }
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
            const palette = echarts.theme?.default?.color ?? [
                '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
                '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc'
            ];
            runColors.set(run, palette[runColors.size % palette.length]);
        }
        return runColors.get(run);
    }

    function renderVisible() {
        document.querySelectorAll('[data-metric]').forEach(el => {
            if (dataCache.has(el.dataset.metric)) renderChart(el);
        });
    }

    // Shared series builder — used by both renderChart and openModal
    function buildSeries(path) {
        const EPS = 1e-10;
        return Object.entries(dataCache.get(path) ?? {}).map(([run, { x, y }]) => ({
            name: run, type: 'line',
            data: x.map((v, i) => [
                logX ? Math.max(EPS, v) : v,
                logY ? Math.max(EPS, y[i]) : y[i],
            ]),
            showSymbol: false, animation: false,
            lineStyle: { width: 1.5 },
            itemStyle: { color: colorFor(run) },
        }));
    }

    function renderChart(cardEl) {
        const path = cardEl.dataset.metric;
        const canvas = cardEl.querySelector('.chart-canvas');
        if (!canvas) return;

        const EPS = 1e-10;
        const chart = instances.get(path) ?? (() => {
            const c = echarts.init(canvas, null, { renderer: 'canvas' });
            instances.set(path, c);
            return c;
        })();

        const series = buildSeries(path);
        chart.setOption({
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: tooltipFormatter,
            },
            grid: { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
            xAxis: { type: logX ? 'log' : 'value', scale: true, min: logX ? EPS : undefined },
            yAxis: {
                type: logY ? 'log' : 'value', scale: true, min: logY ? EPS : undefined,
                splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } }
            },
            series,
            legend: {
                bottom: 0, icon: 'circle', type: 'scroll', textStyle: { fontSize: 9 },
                data: series.map(s => ({ name: s.name, itemStyle: { color: colorFor(s.name) } })),
            },
        }, { notMerge: true });
    }

    function tooltipFormatter(params) {
        if (!params.length) return '';
        const rows = params
            .filter(p => p.value?.[1] != null)
            .map(p => `${p.marker} ${p.seriesName}: <b>${p.value[1].toFixed(4)}</b>`)
            .join('<br>');
        return `<small>${params[0].axisValueLabel}</small><br>${rows}`;
    }

    // --- Modal ---

    function openModal(path) {
        if (!dataCache.has(path)) return;

        document.getElementById('chart-modal-title').textContent = path;

        if (modalInstance) { modalInstance.dispose(); modalInstance = null; }

        // Init with explicit dimensions before showing so the chart is already
        // drawn during the open animation — no empty-modal flash.
        const canvas = document.getElementById('chart-modal-canvas');
        const modalW = Math.min(window.innerWidth * 0.85, 1200) - 80;  // approx dialog width minus padding
        modalInstance = echarts.init(canvas, null, { renderer: 'canvas', width: modalW, height: 520 });

        const EPS = 1e-10;
        const series = buildSeries(path);
        modalInstance.setOption({
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: tooltipFormatter,
            },
            grid: { left: '8%', right: '4%', top: '8%', bottom: '22%', containLabel: true },
            xAxis: { type: logX ? 'log' : 'value', scale: true, min: logX ? EPS : undefined },
            yAxis: {
                type: logY ? 'log' : 'value', scale: true, min: logY ? EPS : undefined,
                splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } }
            },
            dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: '8%' }],
            series,
            legend: {
                bottom: 0, icon: 'circle', type: 'scroll', textStyle: { fontSize: 9 },
                data: series.map(s => ({ name: s.name, itemStyle: { color: colorFor(s.name) } })),
            },
        }, { notMerge: true });

        UIkit.modal('#chart-modal').show();

        // Correct any dimension mismatch once animation settles
        document.getElementById('chart-modal').addEventListener('shown', () => {
            modalInstance?.resize();
        }, { once: true });
    }

    // Dispose when UIkit closes the modal (backdrop click, Escape, or Close button)
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('chart-modal')?.addEventListener('hidden', () => {
            if (modalInstance) { modalInstance.dispose(); modalInstance = null; }
        });
    });

    // --- Settings ---

    function setLogAxes(x, y) {
        logX = x; logY = y;
        renderVisible();
        // Re-render modal chart with updated axis type if open
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

    document.addEventListener('htmx:afterSettle', () => {
        const island = document.getElementById('chart-data-payload');
        if (!island) return;
        observeAll();
        const raw = JSON.parse(island.textContent);
        if (!raw.data) return;
        const { data, runs, schema_changed } = raw;
        if (schema_changed) {
            instances.forEach(c => c.dispose());
            instances.clear();
            runColors.clear();
        }
        pruneRuns(runs);
        ingestData(data);
    });

    document.addEventListener('htmx:beforeSwap', e => {
        if (e.detail.target === document.body) {
            instances.forEach(c => c.dispose());
            instances.clear();
        }
    });

    // SSE data events
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
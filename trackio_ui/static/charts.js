const Charts = (() => {
    const instances = new Map();  // metricPath -> ECharts instance
    const dataCache = new Map();  // metricPath -> { runName: {x, y} }
    let logX = false, logY = false;

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

    function renderVisible() {
        document.querySelectorAll('[data-metric]').forEach(el => {
            if (dataCache.has(el.dataset.metric)) renderChart(el);
        });
    }

    function renderChart(cardEl) {
        const path = cardEl.dataset.metric;
        const canvas = cardEl.querySelector('.chart-canvas');
        if (!canvas) return;

        const chart = instances.get(path) ?? (() => {
            const c = echarts.init(canvas, null, { renderer: 'canvas' });
            instances.set(path, c);
            return c;
        })();

        const series = Object.entries(dataCache.get(path) ?? {}).map(([run, { x, y }]) => ({
            name: run, type: 'line',
            data: x.map((v, i) => [v, y[i]]),
            showSymbol: false, animation: false,
            lineStyle: { width: 1.5 },
        }));

        chart.setOption({
            animation: false,
            tooltip: {
                trigger: 'axis', confine: true,
                axisPointer: { type: 'line', animation: false },
                formatter: tooltipFormatter,
            },
            grid: { left: '8%', right: '4%', top: '10%', bottom: '15%', containLabel: true },
            xAxis: { type: logX ? 'log' : 'value', scale: true },
            yAxis: {
                type: logY ? 'log' : 'value', scale: true,
                splitLine: { lineStyle: { type: 'dashed', opacity: 0.05 } }
            },
            series,
            legend: { bottom: 0, icon: 'circle', type: 'scroll', textStyle: { fontSize: 9 } },
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

    // --- Settings ---

    function setLogAxes(x, y) {
        logX = x; logY = y;
        renderVisible();
    }

    // --- Resize ---

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => instances.forEach(c => c.resize()), 150);
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

    return { observeAll, ingestData, pruneRuns, setLogAxes, getCurrentSchema: () => [...instances.keys()] };
})();

document.addEventListener('DOMContentLoaded', Charts.observeAll);

document.addEventListener('htmx:configRequest', e => {
    if (!e.detail.path.includes('/layout')) return;
    Charts.getCurrentSchema().forEach(path =>
        e.detail.parameters.append('current_schema', path)
    );
});
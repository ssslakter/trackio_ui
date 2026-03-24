document.addEventListener('htmx:sseOpen', e => {
    e.detail.source.addEventListener('data_update', ev => {
        const payload = JSON.parse(ev.data);
        document.dispatchEvent(new CustomEvent('charts:live_data', { detail: payload }));
    });
});

function stopSSE() {
    const root = document.getElementById('sse-root');
    if (root) root.removeAttribute('sse-connect');
}
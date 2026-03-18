// sse.js — SSE lifecycle manager
// Works alongside the htmx-ext-sse extension.
// htmx handles layout_add / layout_remove / runs_finished via sse-swap on the #sse-root element.
// This file only handles data_update, which carries JSON not HTML.

document.addEventListener('htmx:sseOpen', e => {
    e.detail.source.addEventListener('data_update', ev => {
        const payload = JSON.parse(ev.data).data;
        document.dispatchEvent(new CustomEvent('charts:data', { detail: payload }));
    });
});

// Called by Alpine when liveMode turns off or runs change — closes the SSE connection cleanly.
// htmx-ext-sse listens for the sse-root element being removed/replaced and closes automatically,
// but we can also force it by swapping in a fresh element without sse-connect.
function stopSSE() {
    const root = document.getElementById('sse-root');
    if (root) root.removeAttribute('sse-connect');
}
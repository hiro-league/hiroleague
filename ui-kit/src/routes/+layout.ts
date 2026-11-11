// Client-side app: pages are prerendered to static shells (relative asset paths), then run in the
// browser. The backend serves the files; there is no Node server.
export const ssr = false;
export const prerender = true;

/**
 * Cloudflare Worker — dumb CORS relay for HubSpot
 *
 * No secrets stored here. Your HubSpot token stays in your browser and is
 * forwarded as-is. This worker only adds the CORS headers that HubSpot's API
 * omits, allowing browser-direct calls.
 *
 * Setup (~2 min):
 *   1. workers.cloudflare.com → free account → Create Worker
 *   2. Paste this file → Save & Deploy  (no env vars / secrets needed)
 *   3. Copy the worker URL  (e.g. https://hs-relay.YOUR-NAME.workers.dev)
 *   4. In the app → Settings → paste it as "Proxy URL"
 */

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age':       '86400',
};

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url   = new URL(request.url);
    const hsUrl = 'https://api.hubapi.com' + url.pathname + url.search;

    const init = {
      method:  request.method,
      headers: {
        // Forward the browser's Authorization header — token never stored here
        'Authorization': request.headers.get('Authorization') || '',
        'Content-Type':  'application/json',
      },
    };
    if (request.method === 'POST') {
      init.body = await request.text();
    }

    try {
      const resp = await fetch(hsUrl, init);
      const body = await resp.text();
      return new Response(body, {
        status:  resp.status,
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502,
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }
  },
};

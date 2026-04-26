/**
 * Cloudflare Worker — HubSpot CORS proxy for Demo Prep
 *
 * Setup (one-time, ~3 min):
 *   1. Go to https://workers.cloudflare.com → sign up free → Create Worker
 *   2. Paste this entire file, click Save & Deploy
 *   3. Settings → Variables → add Secret: HUBSPOT_TOKEN = your HubSpot private-app token
 *   4. Copy the worker URL (e.g. https://demo-prep-proxy.YOUR-NAME.workers.dev)
 *   5. Paste it into the app Settings → Proxy URL field
 *
 * The HubSpot token never touches the browser — it lives here as an env secret.
 */

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age':       '86400',
};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (!env.HUBSPOT_TOKEN) {
      return new Response(JSON.stringify({ error: 'HUBSPOT_TOKEN secret not set in Worker' }), {
        status: 500, headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }

    const url  = new URL(request.url);
    const hsUrl = 'https://api.hubapi.com' + url.pathname + url.search;

    const init = {
      method:  request.method,
      headers: {
        'Authorization': `Bearer ${env.HUBSPOT_TOKEN}`,
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
        status: 502, headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }
  },
};

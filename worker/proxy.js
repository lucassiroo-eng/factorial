/**
 * Cloudflare Worker — dumb CORS relay for HubSpot
 * Paste this in the Cloudflare web editor (no wrangler needed).
 *
 * No secrets stored here. Your HubSpot token stays in your browser
 * and is forwarded as-is. This worker only adds the CORS headers
 * that HubSpot's API omits for browser requests.
 *
 * Setup:
 *   1. workers.cloudflare.com → free account → Create Worker
 *   2. Paste this file → Save & Deploy  (no env vars needed)
 *   3. Copy the worker URL (e.g. https://hs-relay.YOUR-NAME.workers.dev)
 *   4. In the app → Settings → paste it as "Proxy URL"
 */

const CORS_HEADERS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Max-Age':       '86400',
};

addEventListener('fetch', function(event) {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  var url   = new URL(request.url);
  var hsUrl = 'https://api.hubapi.com' + url.pathname + url.search;

  var init = {
    method:  request.method,
    headers: {
      'Authorization': request.headers.get('Authorization') || '',
      'Content-Type':  'application/json',
    },
  };

  if (request.method === 'POST') {
    init.body = await request.text();
  }

  try {
    var resp = await fetch(hsUrl, init);
    var body = await resp.text();
    return new Response(body, {
      status:  resp.status,
      headers: Object.assign({ 'Content-Type': 'application/json' }, CORS_HEADERS),
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status:  502,
      headers: Object.assign({ 'Content-Type': 'application/json' }, CORS_HEADERS),
    });
  }
}

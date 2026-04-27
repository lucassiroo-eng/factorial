/**
 * Cloudflare Worker — proxy seguro para HubSpot + GitHub Actions
 *
 * Los secrets se guardan en Cloudflare (nunca en el código ni en el browser).
 * Setup:
 *   1. Despliega este Worker (Workers & Pages → Create → Worker → pega y guarda)
 *   2. Dashboard → tu Worker → Settings → Variables → Add variable (tipo Secret):
 *        HUBSPOT_API_KEY  → tu token de HubSpot Private App
 *        GITHUB_TOKEN     → tu GitHub PAT (scopes: repo + workflow)
 *   3. En la app → Settings → pon solo la URL del Worker
 *
 * Rutas:
 *   /gh/*   → proxy a https://api.github.com/*  (usa GITHUB_TOKEN)
 *   /*      → proxy a https://api.hubapi.com/*  (usa HUBSPOT_API_KEY)
 */

var CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age':       '86400',
};

addEventListener('fetch', function(event) {
  event.respondWith(handle(event.request));
});

async function handle(request) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS });
  }

  var url  = new URL(request.url);
  var path = url.pathname;

  if (path.startsWith('/gh/')) {
    return proxyGitHub(request, url);
  }
  return proxyHubSpot(request, url);
}

async function proxyHubSpot(request, url) {
  var target = 'https://api.hubapi.com' + url.pathname + url.search;
  var init = {
    method:  request.method,
    headers: {
      'Authorization': 'Bearer ' + HUBSPOT_API_KEY,
      'Content-Type':  'application/json',
    },
  };
  if (request.method === 'POST' || request.method === 'PATCH') {
    init.body = await request.text();
  }
  try {
    var resp = await fetch(target, init);
    var body = await resp.text();
    return new Response(body, {
      status:  resp.status,
      headers: Object.assign({ 'Content-Type': 'application/json' }, CORS),
    });
  } catch (e) {
    return json502(e.message);
  }
}

async function proxyGitHub(request, url) {
  var ghPath = url.pathname.slice(3); // strip /gh
  var target = 'https://api.github.com' + ghPath + url.search;
  var init = {
    method:  request.method,
    headers: {
      'Authorization': 'Bearer ' + GITHUB_TOKEN,
      'Accept':        'application/vnd.github+json',
      'Content-Type':  'application/json',
      'User-Agent':    'factorial-demo-prep-worker',
    },
  };
  if (request.method === 'POST') {
    init.body = await request.text();
  }
  try {
    var resp = await fetch(target, init);
    var body = await resp.text();
    return new Response(body, {
      status:  resp.status,
      headers: Object.assign({ 'Content-Type': 'application/json' }, CORS),
    });
  } catch (e) {
    return json502(e.message);
  }
}

function json502(msg) {
  return new Response(JSON.stringify({ error: msg }), {
    status:  502,
    headers: Object.assign({ 'Content-Type': 'application/json' }, CORS),
  });
}

// NODE: "Build image upload"  (Code node, mode: Run Once for Each Item)
// LinkedIn images are uploaded in two steps: ask for an upload URL, then PUT the bytes there.
// The cover was rendered and stored by the website when the post was approved.
const s = $('Settings').first().json;
const p = $json;
// The website reports its public address; n8n may reach it at another (e.g. host.docker.internal locally).
const publicBase = String(p.siteUrl || '').replace(/\/$/, '');
const coverFetchUrl = publicBase && p.coverUrl.startsWith(publicBase) ? s.siteUrl.replace(/\/$/, '') + p.coverUrl.slice(publicBase.length) : p.coverUrl;
return { json: { ...p, coverFetchUrl, uploadBody: { initializeUploadRequest: { owner: p.me } } } };

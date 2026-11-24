const CACHE='study-shell-v1';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/icon.svg','/manifest.webmanifest']))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{const u=new URL(event.request.url); if(event.request.method!=='GET'||u.origin!==location.origin||u.pathname.startsWith('/api/')||u.pathname==='/health')return; event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(event.request,copy));}return response;}).catch(()=>caches.match(event.request).then(x=>x||caches.match('/'))));});

/* Reproducible local browser QA. Requires playwright; never targets production.
   WK_BASE_URL defaults to loopback. WK_QA_PASSWORD enables merchant screens. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const base = process.env.WK_BASE_URL || 'http://127.0.0.1:8000';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw Error('Local QA only');
const out = path.resolve(process.env.WK_QA_OUTPUT || '.artifacts/browser'); fs.mkdirSync(out, { recursive:true });
let browser;
(async()=>{
 browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}: {})});
 const context = await browser.newContext(); const page = await context.newPage();
 const errors=[]; page.on('pageerror', e=>errors.push(e.message));
 let routes=['/','/productos/','/smart-fit/','/guide/','/cart/','/panel/login/','/tiendas/','/explorar/','/buscar/','/comparar/','/cuenta/','/cuenta/looks/','/para-negocios/','/plataforma/componentes/','/s/wiener-kingdom/','/s/wiener-kingdom/coleccion/','/s/wiener-kingdom/tallas/','/s/wiener-kingdom/looklab/','/s/wiener-kingdom/asesor/','/s/wiener-kingdom/carrito/','/s/wiener-kingdom/ayuda/','/s/estudio-nube/','/s/mercado-demo/'];
 await page.goto(base+'/s/wiener-kingdom/coleccion/');
 const products=await page.locator('a[href*="/producto/"]').evaluateAll(els=>[...new Set(els.map(e=>new URL(e.href).pathname))]);
 routes.push(...products);
 if(process.env.WK_QA_PASSWORD){
   await page.goto(base+'/panel/login/'); await page.locator('[name=username]').fill(process.env.WK_QA_USER||'demo_staff'); await page.locator('[name=password]').fill(process.env.WK_QA_PASSWORD);
   await Promise.all([page.waitForURL(u=>!u.pathname.endsWith('/login/')),page.locator('button[type=submit]').click()]);
   routes.push(...['','catalogo/','catalogo/nuevo/','pedidos/','clientes/','finanzas/','logistica/','configuracion/','diseno/','estadisticas/'].map(r=>'/negocio/wiener-kingdom/'+r));
   await page.goto(base+'/negocio/wiener-kingdom/pedidos/');
   const orders=await page.locator('table a[href*="/pedidos/"]').evaluateAll(els=>els.slice(0,2).map(e=>new URL(e.href).pathname));
   routes.push(...orders,...orders.map(route=>route+'envios/'));
 }
 if(process.env.WK_QA_ROUTES) routes=process.env.WK_QA_ROUTES.split(',');
 routes.push('/cuenta/ingresar/','/cuenta/registro/');
 const results=[];
 for(const width of [390,768,1440]){
   await page.setViewportSize({width,height:960});
   for(const route of routes){
    const response=await page.goto(base+route,{waitUntil:'networkidle'});
    await page.evaluate(()=>document.fonts.ready);
    const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,brokenImages:[...document.images].filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.getAttribute('src')),overflow:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+2&&!e.closest('.compare-scroll,.table-wrap')).slice(0,5).map(e=>e.tagName+'.'+e.className)}));
    results.push({route,width,status:response.status(),...layout});
    if(['/cuenta/','/s/wiener-kingdom/','/plataforma/componentes/','/negocio/wiener-kingdom/estadisticas/','/s/wiener-kingdom/coleccion/'].includes(route)) await page.screenshot({path:path.join(out,route.replaceAll('/','_')+width+'.png'),fullPage:true});
   }
 }
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({results,errors},null,2));
 const failed=results.filter(r=>r.status>=400||r.scroll>r.width+2||r.brokenImages.length);
 console.log(JSON.stringify({pages:results.length,failures:failed,jsErrors:errors},null,2));
 await browser.close(); if(failed.length||errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser) await browser.close();});

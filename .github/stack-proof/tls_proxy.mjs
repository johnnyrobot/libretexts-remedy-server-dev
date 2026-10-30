// Private TLS termination fixture, forwarding to the unmodified compiled app.
// No auth, responses or cookies are manufactured; no forwarded-header trust.
import https from 'node:https';
import http from 'node:http';
import fs from 'node:fs';
const server=https.createServer({key:fs.readFileSync('/fixtures/key.pem'),cert:fs.readFileSync('/fixtures/cert.pem')},(req,res)=>{
  const headers={...req.headers};
  delete headers.forwarded;delete headers['x-forwarded-for'];delete headers['x-forwarded-host'];delete headers['x-forwarded-proto'];
  const upstream=http.request({hostname:'conductor',port:5000,path:req.url,method:req.method,headers,timeout:120000},reply=>{
    res.writeHead(reply.statusCode,reply.headers);reply.pipe(res);
  });
  upstream.on('timeout',()=>upstream.destroy());
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502);res.end();});
  req.on('aborted',()=>upstream.destroy());req.pipe(upstream);
});
server.requestTimeout=125000;server.headersTimeout=10000;
server.listen(8443,'0.0.0.0');
for(const signal of ['SIGTERM','SIGINT'])process.once(signal,()=>server.close());

// First-user localhost exception only on this proof's fresh disposable database.
// Credentials are read from a private UID-owned FILE, never argv or printed.
const fs = require('fs');
const info = fs.statSync('/run/bootstrap/credentials.json');
if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077)) throw Error('private bootstrap file required');
const credentials = JSON.parse(fs.readFileSync('/run/bootstrap/credentials.json', 'utf8'));
const admin = db.getSiblingDB('admin');
// createUser fails closed once any prior administrator closes the localhost exception.
admin.createUser({user:'bootstrap',pwd:credentials.admin,roles:[{role:'root',db:'admin'}]});
if (!admin.auth('bootstrap',credentials.admin)) throw Error('bootstrap authentication failed');
const app = db.getSiblingDB('conductor_synthetic');
app.createUser({user:'conductor',pwd:credentials.application,roles:[{role:'readWrite',db:'conductor_synthetic'}]});
admin.logout();
let anonymousDenied=false;
try { app.getCollection('projects').findOne(); } catch (error) { if (error.code===13) anonymousDenied=true; else throw error; }
if (!anonymousDenied) throw Error('anonymous database access was not denied');
print(JSON.stringify({authenticatedBootstrap:true,anonymousReadDenied:true,applicationRole:'readWrite'}));

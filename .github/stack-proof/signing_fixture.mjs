// Ephemeral synthetic Ed25519 inputs for isolated CI only. No real keys loaded.
import fs from 'node:fs';
import {generateKeyPairSync,randomUUID} from 'node:crypto';
const directory=process.argv[2];
const pair=generateKeyPairSync('ed25519');
const common={issuer:'urn:conductor:lt197',audience:'urn:bridge:lt197',trust_epoch:'lt197-synthetic-epoch'};
const kid='lt197-'+randomUUID();
fs.writeFileSync(directory+'/private.pem',pair.privateKey.export({type:'pkcs8',format:'pem'}),{mode:0o400});
for(const environment of ['test','production'])fs.writeFileSync(directory+'/'+environment+'.json',JSON.stringify({...common,environment,keys:[{...common,environment,kid,kty:'OKP',crv:'Ed25519',x:pair.publicKey.export({format:'jwk'}).x,not_before:0,not_after:4102444800,enabled:true,revoked_at:null}]}),{mode:0o400});
fs.writeFileSync(directory+'/metadata.json',JSON.stringify({...common,kid}),{mode:0o400});

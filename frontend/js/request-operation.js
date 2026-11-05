// Technical retry metadata only: never store the form, user ID or session credentials.
const STORAGE='mgimov-request-operation-v1';
const TYPES=['study_certificate','general_certificate','appeal'];
const LIFETIME=24*60*60*1000;
export function createRequestOperations({getStorage=()=>globalThis.sessionStorage,crypto=globalThis.crypto,now=Date.now}={}){
  async function tag(owner,key){
    const bytes=new TextEncoder().encode('mgimov:request:v1\0'+owner+'\0'+key);
    return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
  }
  return {
    async restore(owner){
      try{
        const raw=getStorage().getItem(STORAGE);if(!raw)return {state:'none'};
        const entry=JSON.parse(raw);
        if(!entry || Object.keys(entry).sort().join(',')!=='expiresAt,key,tag,type,v' || entry.v!==1 || !/^[a-f0-9]{32}$/.test(entry.key) || !/^[a-f0-9]{64}$/.test(entry.tag) || !TYPES.includes(entry.type) || !Number.isFinite(entry.expiresAt))return {state:'lost'};
        if(entry.tag!==await tag(owner,entry.key))return {state:'mismatch'};
        if(entry.expiresAt<=now() || entry.expiresAt>now()+LIFETIME)return {state:'lost'};
        return {state:'pending',entry};
      }catch{return {state:'unavailable'};}
    },
    async save(owner,type,key,current=()=>true){
      const entry={v:1,key,type,tag:await tag(owner,key),expiresAt:now()+LIFETIME};
      if(!current())return false;
      const raw=JSON.stringify(entry),storage=getStorage();storage.setItem(STORAGE,raw);
      if(storage.getItem(STORAGE)!==raw)throw new Error('Retry storage unavailable');
      return true;
    },
    remove(key){
      try{
        const storage=getStorage();
        if(key){const raw=storage.getItem(STORAGE);if(raw && JSON.parse(raw).key!==key)return;}
        storage.removeItem(STORAGE);
      }catch{/* Failing closed on the next restore/save; never print metadata. */}
    }
  };
}

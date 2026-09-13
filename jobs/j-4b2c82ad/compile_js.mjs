import fs from 'fs';
import crypto from 'crypto';
const SRC_SHA='ab3b7afc2634bdd6f2939355e7d47e355ae2bd06a99bae84b00bf3b8a3746736';
function die(m){throw new Error(m)}
function canon(x){
  if(Array.isArray(x)) return '['+x.map(canon).join(',')+']';
  if(x!==null && typeof x==='object') return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canon(x[k])).join(',')+'}';
  return JSON.stringify(x);
}
function checkKeys(o,ks,ctx){ if(o===null||typeof o!=='object'||Array.isArray(o))die(ctx+': object'); const a=Object.keys(o).sort(),b=[...ks].sort(); if(a.length!==b.length||a.some((x,i)=>x!==b[i]))die(ctx+': keys'); }
function lowerContract(c,idx){
  checkKeys(c,['a','b','d','i','k','q','s','t','v','z'],'c'+idx);
  if(c.i!==`c${idx}`) die('id'); if(!Array.isArray(c.v))die('vars');
  const env=new Map(); let ni=0,nb=0; const vars=[];
  c.v.forEach((v,j)=>{ if(!Array.isArray(v)||v.length!==2||v[0]!==`v${j}`||!['Int','Bool'].includes(v[1]))die('var decl'); if(env.has(v[0]))die('dup'); if(v[1]==='Int'){env.set(v[0],['Int',ni]);vars.push(['Int',ni++]);}else{env.set(v[0],['Bool',nb]);vars.push(['Bool',nb++]);}});
  function ex(n){
    if(n===null||typeof n!=='object'||Array.isArray(n)||Object.keys(n).length!==1)die('node');
    const op=Object.keys(n)[0], arg=n[op];
    if(op==='var'){ if(!env.has(arg))die('unknown var'); const [s,i]=env.get(arg); return [s,[s==='Int'?'iv':'bv',i]]; }
    if(op==='int'){ if(!Number.isInteger(arg))die('int'); return ['Int',['int',arg]]; }
    if(op==='bool'){ if(typeof arg!=='boolean')die('bool'); return ['Bool',['bool',arg]]; }
    if(['add','sub'].includes(op)){ if(!Array.isArray(arg)||arg.length!==2)die(op); const [s1,a]=ex(arg[0]),[s2,b]=ex(arg[1]); if(s1!=='Int'||s2!=='Int')die(op+' types'); return ['Int',[op,a,b]]; }
    if(op==='ite'){ if(!Array.isArray(arg)||arg.length!==3)die('ite'); const [sc,cx]=ex(arg[0]),[s1,a]=ex(arg[1]),[s2,b]=ex(arg[2]); if(sc!=='Bool'||s1!==s2)die('ite types'); return [s1,[s1==='Int'?'itei':'iteb',cx,a,b]]; }
    if(['eq','ne'].includes(op)){ if(!Array.isArray(arg)||arg.length!==2)die(op); const [s1,a]=ex(arg[0]),[s2,b]=ex(arg[1]); if(s1!==s2)die(op+' types'); return ['Bool',[op+(s1==='Int'?'i':'b'),a,b]]; }
    if(['lt','le','gt','ge'].includes(op)){ if(!Array.isArray(arg)||arg.length!==2)die(op); const [s1,a]=ex(arg[0]),[s2,b]=ex(arg[1]); if(s1!=='Int'||s2!=='Int')die(op+' types'); return ['Bool',[op,a,b]]; }
    if(op==='not'){ const [s,a]=ex(arg); if(s!=='Bool')die('not type'); return ['Bool',['not',a]]; }
    if(['and','or'].includes(op)){ if(!Array.isArray(arg)||arg.length<1)die(op); const xs=arg.map(y=>{const [s,a]=ex(y);if(s!=='Bool')die(op+' type');return a}); return ['Bool',[op,xs]]; }
    if(['implies','iff'].includes(op)){ if(!Array.isArray(arg)||arg.length!==2)die(op); const [s1,a]=ex(arg[0]),[s2,b]=ex(arg[1]); if(s1!=='Bool'||s2!=='Bool')die(op+' types'); return ['Bool',[op,a,b]]; }
    die('unknown op '+op);
  }
  const be=n=>{const [s,a]=ex(n);if(s!=='Bool')die('expected bool');return a};
  if(!Array.isArray(c.q)||!Array.isArray(c.t)||!Array.isArray(c.k))die('lists');
  const q=c.q.map(be), t=c.t.map(be); if(q.length<1)die('no obligations');
  if(c.k.some(x=>!Number.isInteger(x)||x<0||x>=q.length)||new Set(c.k).size!==c.k.length)die('guard');
  return {id:c.i,vars:vars,ni:ni,nb:nb,d:be(c.d),a:be(c.a),z:be(c.z),s:be(c.s),b:be(c.b),q:q,k:c.k,t:t};
}
function emitI(x){const t=x[0]; if(t==='int')return `(.lit ${x[1]})`; if(t==='iv')return `(.var ${x[1]})`; if(['add','sub'].includes(t))return `(.${t} ${emitI(x[1])} ${emitI(x[2])})`; if(t==='itei')return `(.ite ${emitB(x[1])} ${emitI(x[2])} ${emitI(x[3])})`; die('emitI '+t)}
function foldB(op,xs){ if(xs.length===1)return emitB(xs[0]); let s=emitB(xs[xs.length-1]); for(let i=xs.length-2;i>=0;i--)s=`(.${op} ${emitB(xs[i])} ${s})`; return s; }
function emitB(x){const t=x[0]; if(t==='bool')return x[1]?'(.lit true)':'(.lit false)'; if(t==='bv')return `(.var ${x[1]})`; if(t==='not')return `(.not ${emitB(x[1])})`; if(['and','or'].includes(t))return foldB(t,x[1]); if(t==='implies')return `(.imp ${emitB(x[1])} ${emitB(x[2])})`; if(t==='iff')return `(.iff ${emitB(x[1])} ${emitB(x[2])})`; if(['eqi','nei','lt','le','gt','ge'].includes(t))return `(.${t} ${emitI(x[1])} ${emitI(x[2])})`; if(['eqb','neb'].includes(t))return `(.${t} ${emitB(x[1])} ${emitB(x[2])})`; if(t==='iteb')return `(.ite ${emitB(x[1])} ${emitB(x[2])} ${emitB(x[3])})`; die('emitB '+t)}
function orAll(ns){if(ns.length===1)return ns[0];let s=ns[ns.length-1];for(let i=ns.length-2;i>=0;i--)s=`(.or ${ns[i]} ${s})`;return s}
function emitLean(ir){const L=['import IRSemantics','','namespace G','open IR','']; ir.contracts.forEach((c,ci)=>{const p=`c${ci}`; for(const key of ['d','a','z','s','b'])L.push(`def ${p}${key} : BExpr := ${emitB(c[key])}`); c.q.forEach((q,j)=>L.push(`def ${p}q${j} : BExpr := ${emitB(q)}`)); c.t.forEach((t,j)=>L.push(`def ${p}t${j} : BExpr := ${emitB(t)}`)); L.push(`def ${p}all : BExpr := ${orAll(c.q.map((_,j)=>p+'q'+j))}`); const gs=c.k.map(j=>p+'q'+j); L.push(`def ${p}guard : BExpr := ${gs.length?orAll(gs):'(.lit false)'}`); L.push(`def ${p} : Contract := { domain := ${p}d, intent := ${p}a, initial := ${p}z, candidate := ${p}s, seeded := ${p}b, obligations := [${c.q.map((_,j)=>p+'q'+j).join(', ')}], currentGuard := ${p}guard, threats := [${c.t.map((_,j)=>p+'t'+j).join(', ')}], intCount := ${c.ni}, boolCount := ${c.nb} }`); L.push(''); }); L.push('def bank : List Contract := ['+ir.contracts.map((_,i)=>'c'+i).join(', ')+']','','end G',''); return L.join('\n'); }
const src=process.argv[2], outdir=process.argv[3]; fs.mkdirSync(outdir,{recursive:true}); const rawb=fs.readFileSync(src), h=crypto.createHash('sha256').update(rawb).digest('hex'); if(h!==SRC_SHA)die('source digest '+h); const raw=JSON.parse(rawb.toString('utf8')); checkKeys(raw,['s','c'],'top'); if(raw.s!=='opaque.qf-lia-bool.v1'||!Array.isArray(raw.c)||raw.c.length!==6)die('top values'); const cs=raw.c.map(lowerContract); const ir={schema:'pc.typed-ir.v1',source_sha256:h,contracts:cs}; const irtxt=canon(ir)+'\n', lean=emitLean(ir); fs.writeFileSync(outdir+'/typed_ir.json',irtxt);fs.writeFileSync(outdir+'/GeneratedBank.lean',lean); const manifest={schema:'pc.compiler-output.v1',source_sha256:h,typed_ir_sha256:crypto.createHash('sha256').update(irtxt).digest('hex'),lean_sha256:crypto.createHash('sha256').update(lean).digest('hex'),contracts:cs.length,expressions:cs.reduce((n,c)=>n+5+c.q.length+c.t.length,0)}; fs.writeFileSync(outdir+'/manifest.json',canon(manifest)+'\n'); console.log(canon(manifest));

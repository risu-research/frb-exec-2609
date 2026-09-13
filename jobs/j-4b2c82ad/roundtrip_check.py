import json, hashlib, sys
from pathlib import Path
SRC_SHA='ab3b7afc2634bdd6f2939355e7d47e355ae2bd06a99bae84b00bf3b8a3746736'
def canon(x): return json.dumps(x,sort_keys=True,separators=(',',':'))
def main():
    srcp=Path(sys.argv[1]); irp=Path(sys.argv[2])
    rawb=srcp.read_bytes(); assert hashlib.sha256(rawb).hexdigest()==SRC_SHA
    src=json.loads(rawb); ir=json.loads(irp.read_text())
    assert ir['schema']=='pc.typed-ir.v1' and ir['source_sha256']==SRC_SHA and len(ir['contracts'])==len(src['c'])==6
    out=[]
    for n,(sc,tc) in enumerate(zip(src['c'],ir['contracts'])):
        assert tc['id']==f'c{n}'==sc['i']
        imap={}; bmap={}; vv=[]
        for j,(sort,ix) in enumerate(tc['vars']):
            name=f'v{j}'; vv.append([name,sort]); (imap if sort=='Int' else bmap)[ix]=name
        assert vv==sc['v']
        def ri(x):
            t=x[0]
            if t=='int': return {'int':x[1]}
            if t=='iv': return {'var':imap[x[1]]}
            if t in ('add','sub'): return {t:[ri(x[1]),ri(x[2])]}
            if t=='itei': return {'ite':[rb(x[1]),ri(x[2]),ri(x[3])]}
            raise AssertionError(('ri',t))
        def rb(x):
            t=x[0]
            if t=='bool': return {'bool':x[1]}
            if t=='bv': return {'var':bmap[x[1]]}
            if t=='not': return {'not':rb(x[1])}
            if t in ('and','or'): return {t:[rb(y) for y in x[1]]}
            if t=='implies': return {'implies':[rb(x[1]),rb(x[2])]}
            if t=='iff': return {'iff':[rb(x[1]),rb(x[2])]}
            if t in ('eqi','eqb'):
                f=ri if t=='eqi' else rb; return {'eq':[f(x[1]),f(x[2])]}
            if t in ('nei','neb'):
                f=ri if t=='nei' else rb; return {'ne':[f(x[1]),f(x[2])]}
            if t in ('lt','le','gt','ge'): return {t:[ri(x[1]),ri(x[2])]}
            if t=='iteb': return {'ite':[rb(x[1]),rb(x[2]),rb(x[3])]}
            raise AssertionError(('rb',t))
        rec={'i':tc['id'],'v':vv,'d':rb(tc['d']),'a':rb(tc['a']),'z':rb(tc['z']),'s':rb(tc['s']),'b':rb(tc['b']),'q':[rb(x) for x in tc['q']],'k':tc['k'],'t':[rb(x) for x in tc['t']]}
        expected={k:sc[k] for k in ['i','v','d','a','z','s','b','q','k','t']}
        if canon(rec)!=canon(expected): raise SystemExit('ROUNDTRIP_MISMATCH:'+str(n))
        out.append(rec)
    semantic={'s':src['s'],'c':out}
    if canon(semantic)!=canon(src): raise SystemExit('FULL_ROUNDTRIP_MISMATCH')
    print(json.dumps({'schema':'pc.roundtrip.v1','source_sha256':SRC_SHA,'contracts':6,'exact_semantic_roundtrip':True},sort_keys=True))
if __name__=='__main__': main()

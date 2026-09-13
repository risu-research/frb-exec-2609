import json, hashlib, sys
from pathlib import Path
SRC_SHA='ab3b7afc2634bdd6f2939355e7d47e355ae2bd06a99bae84b00bf3b8a3746736'

class Reject(Exception): pass

def canon(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def check_keys(o, keys, ctx):
    if not isinstance(o,dict) or set(o)!=set(keys): raise Reject(f'{ctx}: keys')

def lower_contract(c, idx):
    check_keys(c,['a','b','d','i','k','q','s','t','v','z'],f'c{idx}')
    if c['i']!=f'c{idx}': raise Reject('id')
    if not isinstance(c['v'],list): raise Reject('vars')
    env={}; ni=nb=0; vars_out=[]
    for j,v in enumerate(c['v']):
        if not (isinstance(v,list) and len(v)==2 and v[0]==f'v{j}' and v[1] in ('Int','Bool')): raise Reject('var decl')
        if v[0] in env: raise Reject('dup var')
        if v[1]=='Int': env[v[0]]=('Int',ni); vars_out.append(['Int',ni]); ni+=1
        else: env[v[0]]=('Bool',nb); vars_out.append(['Bool',nb]); nb+=1
    def ex(n):
        if not isinstance(n,dict) or len(n)!=1: raise Reject(f'node {n!r}')
        op,arg=next(iter(n.items()))
        if op=='var':
            if arg not in env: raise Reject('unknown var')
            s,i=env[arg]; return s, [('iv' if s=='Int' else 'bv'),i]
        if op=='int':
            if type(arg) is not int: raise Reject('int')
            return 'Int',['int',arg]
        if op=='bool':
            if type(arg) is not bool: raise Reject('bool')
            return 'Bool',['bool',arg]
        if op in ('add','sub'):
            if not isinstance(arg,list) or len(arg)!=2: raise Reject(op)
            s1,a=ex(arg[0]); s2,b=ex(arg[1])
            if s1!='Int' or s2!='Int': raise Reject(op+' types')
            return 'Int',[op,a,b]
        if op=='ite':
            if not isinstance(arg,list) or len(arg)!=3: raise Reject('ite')
            sc,cx=ex(arg[0]); s1,a=ex(arg[1]); s2,b=ex(arg[2])
            if sc!='Bool' or s1!=s2: raise Reject('ite types')
            return s1,[('itei' if s1=='Int' else 'iteb'),cx,a,b]
        if op in ('eq','ne'):
            if not isinstance(arg,list) or len(arg)!=2: raise Reject(op)
            s1,a=ex(arg[0]); s2,b=ex(arg[1])
            if s1!=s2: raise Reject(op+' types')
            return 'Bool',[op+('i' if s1=='Int' else 'b'),a,b]
        if op in ('lt','le','gt','ge'):
            if not isinstance(arg,list) or len(arg)!=2: raise Reject(op)
            s1,a=ex(arg[0]); s2,b=ex(arg[1])
            if s1!='Int' or s2!='Int': raise Reject(op+' types')
            return 'Bool',[op,a,b]
        if op=='not':
            s,a=ex(arg)
            if s!='Bool': raise Reject('not type')
            return 'Bool',['not',a]
        if op in ('and','or'):
            if not isinstance(arg,list) or len(arg)<1: raise Reject(op)
            xs=[]
            for y in arg:
                s,a=ex(y)
                if s!='Bool': raise Reject(op+' type')
                xs.append(a)
            return 'Bool',[op,xs]
        if op in ('implies','iff'):
            if not isinstance(arg,list) or len(arg)!=2: raise Reject(op)
            s1,a=ex(arg[0]); s2,b=ex(arg[1])
            if s1!='Bool' or s2!='Bool': raise Reject(op+' types')
            return 'Bool',[op,a,b]
        raise Reject('unknown op '+op)
    def be(n):
        s,a=ex(n)
        if s!='Bool': raise Reject('expected bool')
        return a
    q=c['q']; t=c['t']; k=c['k']
    if not isinstance(q,list) or not isinstance(t,list) or not isinstance(k,list): raise Reject('lists')
    qo=[be(x) for x in q]; to=[be(x) for x in t]
    if len(qo)<1: raise Reject('no obligations')
    if any(type(x) is not int or x<0 or x>=len(qo) for x in k) or len(set(k))!=len(k): raise Reject('guard')
    return {'id':c['i'],'vars':vars_out,'ni':ni,'nb':nb,
            'd':be(c['d']),'a':be(c['a']),'z':be(c['z']),'s':be(c['s']),'b':be(c['b']),
            'q':qo,'k':k,'t':to}

def emit_i(x):
    tag=x[0]
    if tag=='int': return f'(.lit {x[1]})'
    if tag=='iv': return f'(.var {x[1]})'
    if tag in ('add','sub'): return f'(.{tag} {emit_i(x[1])} {emit_i(x[2])})'
    if tag=='itei': return f'(.ite {emit_b(x[1])} {emit_i(x[2])} {emit_i(x[3])})'
    raise Reject('emit_i '+tag)

def foldb(op,xs):
    if len(xs)==1: return emit_b(xs[0])
    s=emit_b(xs[-1])
    for x in reversed(xs[:-1]): s=f'(.{op} {emit_b(x)} {s})'
    return s

def emit_b(x):
    tag=x[0]
    if tag=='bool': return '(.lit true)' if x[1] else '(.lit false)'
    if tag=='bv': return f'(.var {x[1]})'
    if tag=='not': return f'(.not {emit_b(x[1])})'
    if tag in ('and','or'): return foldb(tag,x[1])
    if tag=='implies': return f'(.imp {emit_b(x[1])} {emit_b(x[2])})'
    if tag=='iff': return f'(.iff {emit_b(x[1])} {emit_b(x[2])})'
    if tag in ('eqi','nei','lt','le','gt','ge'): return f'(.{tag} {emit_i(x[1])} {emit_i(x[2])})'
    if tag in ('eqb','neb'): return f'(.{tag} {emit_b(x[1])} {emit_b(x[2])})'
    if tag=='iteb': return f'(.ite {emit_b(x[1])} {emit_b(x[2])} {emit_b(x[3])})'
    raise Reject('emit_b '+tag)

def or_all(names):
    if len(names)==1: return names[0]
    s=names[-1]
    for n in reversed(names[:-1]): s=f'(.or {n} {s})'
    return s

def emit_lean(ir):
    L=['import IRSemantics','','namespace G','open IR','']
    for ci,c in enumerate(ir['contracts']):
        p=f'c{ci}'
        for key in ['d','a','z','s','b']:
            L.append(f'def {p}{key} : BExpr := {emit_b(c[key])}')
        for j,q in enumerate(c['q']): L.append(f'def {p}q{j} : BExpr := {emit_b(q)}')
        for j,t in enumerate(c['t']): L.append(f'def {p}t{j} : BExpr := {emit_b(t)}')
        L.append(f'def {p}all : BExpr := {or_all([p+"q"+str(j) for j in range(len(c["q"]))])}')
        gnames=[p+'q'+str(j) for j in c['k']]
        L.append(f'def {p}guard : BExpr := {or_all(gnames) if gnames else "(.lit false)"}')
        L.append(f'def {p} : Contract := {{ domain := {p}d, intent := {p}a, initial := {p}z, candidate := {p}s, seeded := {p}b, obligations := [{", ".join(p+"q"+str(j) for j in range(len(c["q"])))}], currentGuard := {p}guard, threats := [{", ".join(p+"t"+str(j) for j in range(len(c["t"])))}], intCount := {c["ni"]}, boolCount := {c["nb"]} }}')
        L.append('')
    L.append('def bank : List Contract := ['+', '.join(f'c{i}' for i in range(len(ir['contracts'])))+']')
    L+=['','end G','']
    return '\n'.join(L)

def main():
    src=Path(sys.argv[1]); outdir=Path(sys.argv[2]); outdir.mkdir(parents=True,exist_ok=True)
    rawb=src.read_bytes(); h=hashlib.sha256(rawb).hexdigest()
    if h!=SRC_SHA: raise Reject('source digest '+h)
    raw=json.loads(rawb)
    check_keys(raw,['s','c'],'top')
    if raw['s']!='opaque.qf-lia-bool.v1' or not isinstance(raw['c'],list) or len(raw['c'])!=6: raise Reject('top values')
    cs=[lower_contract(c,i) for i,c in enumerate(raw['c'])]
    ir={'schema':'pc.typed-ir.v1','source_sha256':h,'contracts':cs}
    irtxt=canon(ir)+'\n'; lean=emit_lean(ir)
    (outdir/'typed_ir.json').write_text(irtxt)
    (outdir/'GeneratedBank.lean').write_text(lean)
    manifest={'schema':'pc.compiler-output.v1','source_sha256':h,'typed_ir_sha256':hashlib.sha256(irtxt.encode()).hexdigest(),'lean_sha256':hashlib.sha256(lean.encode()).hexdigest(),'contracts':len(cs),'expressions':sum(5+len(c['q'])+len(c['t']) for c in cs)}
    (outdir/'manifest.json').write_text(canon(manifest)+'\n')
    print(canon(manifest))
if __name__=='__main__': main()

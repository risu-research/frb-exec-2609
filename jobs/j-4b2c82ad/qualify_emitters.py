from pathlib import Path

PATCHES = {
    'compile_py.py': [
        ("if tag=='int': return f'(.lit {x[1]})'", "if tag=='int': return f'(ITerm.lit {x[1]})'"),
        ("if tag=='iv': return f'(.var {x[1]})'", "if tag=='iv': return f'(ITerm.var {x[1]})'"),
        ("if tag in ('add','sub'): return f'(.{tag} {emit_i(x[1])} {emit_i(x[2])})'", "if tag in ('add','sub'): return f'(ITerm.{tag} {emit_i(x[1])} {emit_i(x[2])})'"),
        ("if tag=='itei': return f'(.ite {emit_b(x[1])} {emit_i(x[2])} {emit_i(x[3])})'", "if tag=='itei': return f'(ITerm.ite {emit_b(x[1])} {emit_i(x[2])} {emit_i(x[3])})'"),
        ("if tag=='bool': return '(.lit true)' if x[1] else '(.lit false)'", "if tag=='bool': return '(BExpr.lit true)' if x[1] else '(BExpr.lit false)'"),
        ("if tag=='bv': return f'(.var {x[1]})'", "if tag=='bv': return f'(BExpr.var {x[1]})'"),
        ("if tag=='not': return f'(.not {emit_b(x[1])})'", "if tag=='not': return f'(BExpr.not {emit_b(x[1])})'"),
        ("s=f'(.{op} {emit_b(x)} {s})'", "s=f'(BExpr.{op} {emit_b(x)} {s})'"),
        ("if tag=='implies': return f'(.imp {emit_b(x[1])} {emit_b(x[2])})'", "if tag=='implies': return f'(BExpr.imp {emit_b(x[1])} {emit_b(x[2])})'"),
        ("if tag=='iff': return f'(.iff {emit_b(x[1])} {emit_b(x[2])})'", "if tag=='iff': return f'(BExpr.iff {emit_b(x[1])} {emit_b(x[2])})'"),
        ("if tag in ('eqi','nei','lt','le','gt','ge'): return f'(.{tag} {emit_i(x[1])} {emit_i(x[2])})'", "if tag in ('eqi','nei','lt','le','gt','ge'): return f'(BExpr.{tag} {emit_i(x[1])} {emit_i(x[2])})'"),
        ("if tag in ('eqb','neb'): return f'(.{tag} {emit_b(x[1])} {emit_b(x[2])})'", "if tag in ('eqb','neb'): return f'(BExpr.{tag} {emit_b(x[1])} {emit_b(x[2])})'"),
        ("if tag=='iteb': return f'(.ite {emit_b(x[1])} {emit_b(x[2])} {emit_b(x[3])})'", "if tag=='iteb': return f'(BExpr.ite {emit_b(x[1])} {emit_b(x[2])} {emit_b(x[3])})'"),
        ("s=f'(.or {n} {s})'", "s=f'(BExpr.or {n} {s})'"),
        ("L.append(f'def {p}guard : BExpr := {or_all(gnames) if gnames else \"(.lit false)\"}')", "L.append(f'def {p}guard : BExpr := {or_all(gnames) if gnames else \"(BExpr.lit false)\"}')"),
    ],
    'compile_js.mjs': [
        ("if(t==='int')return `(.lit ${x[1]})`", "if(t==='int')return `(ITerm.lit ${x[1]})`"),
        ("if(t==='iv')return `(.var ${x[1]})`", "if(t==='iv')return `(ITerm.var ${x[1]})`"),
        ("if(['add','sub'].includes(t))return `(.${t} ${emitI(x[1])} ${emitI(x[2])})`", "if(['add','sub'].includes(t))return `(ITerm.${t} ${emitI(x[1])} ${emitI(x[2])})`"),
        ("if(t==='itei')return `(.ite ${emitB(x[1])} ${emitI(x[2])} ${emitI(x[3])})`", "if(t==='itei')return `(ITerm.ite ${emitB(x[1])} ${emitI(x[2])} ${emitI(x[3])})`"),
        ("if(t==='bool')return x[1]?'(.lit true)':'(.lit false)'", "if(t==='bool')return x[1]?'(BExpr.lit true)':'(BExpr.lit false)'"),
        ("if(t==='bv')return `(.var ${x[1]})`", "if(t==='bv')return `(BExpr.var ${x[1]})`"),
        ("if(t==='not')return `(.not ${emitB(x[1])})`", "if(t==='not')return `(BExpr.not ${emitB(x[1])})`"),
        ("s=`(.${op} ${emitB(xs[i])} ${s})`", "s=`(BExpr.${op} ${emitB(xs[i])} ${s})`"),
        ("if(t==='implies')return `(.imp ${emitB(x[1])} ${emitB(x[2])})`", "if(t==='implies')return `(BExpr.imp ${emitB(x[1])} ${emitB(x[2])})`"),
        ("if(t==='iff')return `(.iff ${emitB(x[1])} ${emitB(x[2])})`", "if(t==='iff')return `(BExpr.iff ${emitB(x[1])} ${emitB(x[2])})`"),
        ("return `(.${t} ${emitI(x[1])} ${emitI(x[2])})`", "return `(BExpr.${t} ${emitI(x[1])} ${emitI(x[2])})`"),
        ("return `(.${t} ${emitB(x[1])} ${emitB(x[2])})`", "return `(BExpr.${t} ${emitB(x[1])} ${emitB(x[2])})`"),
        ("if(t==='iteb')return `(.ite ${emitB(x[1])} ${emitB(x[2])} ${emitB(x[3])})`", "if(t==='iteb')return `(BExpr.ite ${emitB(x[1])} ${emitB(x[2])} ${emitB(x[3])})`"),
        ("s=`(.or ${ns[i]} ${s})`", "s=`(BExpr.or ${ns[i]} ${s})`"),
        ("'(.lit false)'", "'(BExpr.lit false)'"),
    ],
}
for name, patches in PATCHES.items():
    p = Path(name)
    s = p.read_text()
    for old, new in patches:
        if old not in s:
            raise SystemExit(f'EMITTER_NORMALIZATION_INPUT_MISSING:{name}:{old}')
        s = s.replace(old, new, 1)
    p.write_text(s)
print('EMITTER_NORMALIZATION_PASS')

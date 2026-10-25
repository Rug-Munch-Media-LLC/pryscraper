#!/usr/bin/env bash
# Re-runnable dead-code + duplication scan for src/pry (writes /tmp/dc2.json, /tmp/dc4.json).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python3 - <<'PY'
import ast,os,re,json,subprocess,collections
ROOT="src/pry"
def modname(p):
    rel=os.path.relpath(p,"src").replace(os.sep,"/")[:-3]; parts=rel.split("/")
    if parts[-1]=="__init__": parts=parts[:-1]
    return ".".join(parts)
mods={};paths={}
for dp,_,fns in os.walk(ROOT):
    for fn in fns:
        if fn.endswith(".py"):
            p=os.path.join(dp,fn); mods[modname(p)]=p; paths[p]=modname(p)
def ispkg(p): return p.endswith("__init__.py")
edges=collections.defaultdict(set); defs={}; lines={}; main={}; doc={}
for m,p in mods.items():
    src=open(p,encoding="utf-8",errors="replace").read()
    lines[m]=len(src.splitlines())
    try: t=ast.parse(src)
    except Exception as e: print("PARSEFAIL",p); continue
    d=ast.get_docstring(t); doc[m]=(d or "").split("\n")[0][:90]
    main[m]=('if __name__' in src and '__main__' in src)
    pkg=m if ispkg(p) else m.rpartition(".")[0]
    dl=[]
    for node in ast.walk(t):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.col_offset==0:
            dl.append(("async " if isinstance(node,ast.AsyncFunctionDef) else "")+node.name+"("+",".join(x.arg for x in node.args.args)+")")
        elif isinstance(node,ast.ClassDef) and node.col_offset==0: dl.append("class "+node.name)
        elif isinstance(node,ast.Import):
            for a in node.names: edges[a.name].add(m)
        elif isinstance(node,ast.ImportFrom):
            lvl=node.level or 0
            if lvl:
                bp=pkg.split(".") if pkg else []
                if lvl>1: bp=bp[:len(bp)-(lvl-1)]
                tgt=".".join(bp+([node.module] if node.module else []))
            else: tgt=node.module or ""
            if tgt:
                edges[tgt].add(m)
                for a in node.names:
                    if a.name!="*": edges[tgt+"."+a.name].add(m)
    defs[m]=dl
# exact importers only
imp=collections.defaultdict(set)
for t,ss in edges.items():
    if t in mods: imp[t]|=ss
# external exact refs (runtime-ish files only)
ext=collections.defaultdict(set)
rx=re.compile(r'\bpry\.[A-Za-z0-9_.]+')
for dp,dns,fns in os.walk("."):
    dns[:]=[d for d in dns if d not in {".git","node_modules",".venv","venv","__pycache__",".mypy_cache",".ruff_cache","dist","build",".pytest_cache","docs","site_catalog"}]
    for fn in fns:
        p=os.path.join(dp,fn)
        if p.startswith("./src/pry"): continue
        if not re.search(r'\.(py|toml|cfg|ini|yml|yaml|sh|json|txt)$',fn) and "Dockerfile" not in fn and fn!="Makefile": continue
        try: txt=open(p,encoding="utf-8",errors="replace").read()
        except Exception: continue
        for mm in rx.finditer(txt):
            name=mm.group(0).rstrip(".")
            if name in mods: ext[name].add(p)
# dynamic imports
dyn=collections.defaultdict(set)
for m,p in mods.items():
    src=open(p,encoding="utf-8",errors="replace").read()
    if "import_module" in src or "__import__" in src:
        for q in re.findall(r'["\'](pry\.[A-Za-z0-9_.]+)["\']',src): dyn[q].add(p)
dates={}
out=subprocess.run(["git","log","--pretty=format:C|%ad","--date=short","--name-only"],capture_output=True,text=True).stdout
cur=None
for ln in out.splitlines():
    if ln.startswith("C|"): cur=ln[2:]
    elif ln.strip() and cur: dates.setdefault(ln.strip(),cur)
D={}
for m,p in mods.items():
    D[m]={"path":p,"lines":lines.get(m,0),"date":dates.get(p,"?"),"imp":sorted(imp.get(m,set())),
          "ext":sorted(ext.get(m,set())),"dyn":sorted(dyn.get(m,set())),"main":main.get(m,False),
          "pkg":ispkg(p),"defs":defs.get(m,[]),"doc":doc.get(m,"")}
json.dump(D,open("/tmp/dc2.json","w"),indent=1)
dead=[m for m,d in D.items() if not d["imp"] and not d["ext"] and not d["dyn"] and not d["main"] and not d["pkg"]]
deadp=[m for m,d in D.items() if not d["imp"] and not d["ext"] and not d["dyn"] and not d["main"] and d["pkg"]]
mg=[m for m,d in D.items() if d["main"] and not d["imp"] and not d["ext"]]
print("MODS",len(mods),"LINES",sum(lines.values()))
print("DEADFILES",len(dead),"DEADLINES",sum(D[m]['lines'] for m in dead))
print("DEADPKGS",len(deadp),"P KGLINES",sum(D[m]['lines'] for m in deadp))
print("MAINGUARD_UNREF",len(mg))
for m in sorted(dead,key=lambda x:-D[x]["lines"]): print(f"DEAD|{m}|{D[m]['lines']}|{D[m]['date']}|{D[m]['doc'][:70]}")
for m in sorted(deadp,key=lambda x:-D[x]["lines"]): print(f"DEADPKG|{m}|{D[m]['lines']}|{D[m]['date']}|{D[m]['doc'][:60]}")
for m in mg: print(f"MAINGUARD|{m}|{D[m]['lines']}|{D[m]['date']}|{D[m]['doc'][:60]}")
print("== LOW-REF (imp 1-2) files under 60L ==")
low=[m for m,d in D.items() if 1<=len(d["imp"])<=2 and not d["pkg"]]
print(len(low))
for m in sorted(low,key=lambda x:-D[x]["lines"])[:15]: print(f"LOW|{m}|{D[m]['lines']}|imp={D[m]['imp']}")
PY
python3 - <<'PY'
import ast,os,re,json,collections
D=json.load(open("/tmp/dc2.json"))
def ispkg(p): return p.endswith("__init__.py")
def modname(p):
    rel=os.path.relpath(p,"src").replace(os.sep,"/")[:-3]; parts=rel.split("/")
    if parts[-1]=="__init__": parts=parts[:-1]
    return ".".join(parts)
mods=set(D)
# AST external refs from any non-src python file
refs=collections.defaultdict(set); cat={}
SKIP={".git","node_modules",".venv","venv","__pycache__",".mypy_cache",".ruff_cache","dist","build",".pytest_cache","docs"}
for dp,dns,fns in os.walk("."):
    dns[:]=[d for d in dns if d not in SKIP]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p=os.path.join(dp,fn)
        if p.startswith("./src/pry"): continue
        if "site-packages" in p: continue
        c=("tests" if (dp.startswith("./tests") or fn.startswith("test_") or fn=="conftest.py") else
           "actor_factory" if dp.startswith("./actor_factory") else
           "pry_mcp" if dp.startswith("./pry_mcp") else
           "scripts" if dp.startswith("./scripts") else
           "datasets" if dp.startswith("./datasets") else "other")
        cat[p]=c
        try: t=ast.parse(open(p,encoding="utf-8",errors="replace").read())
        except Exception: continue
        for n in ast.walk(t):
            if isinstance(n,ast.Import):
                for a in n.names:
                    if a.name in mods: refs[a.name].add(p)
            elif isinstance(n,ast.ImportFrom):
                if (n.module or "") in mods: refs[n.module].add(p)
                for a in n.names:
                    q=(n.module+"."+a.name) if n.module else a.name
                    if q in mods: refs[q].add(p)
# string mentions inside src (dynamic registry / plugin tables)
srcstr=collections.defaultdict(int)
for m,d in D.items():
    pass
alltext=""
for dp,dns,fns in os.walk("src/pry"):
    for fn in fns:
        if fn.endswith(".py"):
            alltext+=open(os.path.join(dp,fn),encoding="utf-8",errors="replace").read()
out={}
for m,d in D.items():
    r=sorted(refs.get(m,set()))
    cats=collections.Counter(cat[p] for p in r)
    base=m.rpartition(".")[2]
    out[m]={"imp":len(d["imp"]),"refs":r,"cats":dict(cats),"lines":d["lines"],"date":d["date"],
            "path":d["path"],"doc":d["doc"],"pkg":d["pkg"],"main":d["main"],
            "strmention":len(re.findall(r'["\']'+re.escape(base)+r'["\']',alltext)) if len(base)>4 else 0}
json.dump(out,open("/tmp/dc4.json","w"),indent=1)
print("== MODULES WITH ZERO SRC IMPORTERS, non-pkg ==")
z=[m for m,v in out.items() if v["imp"]==0 and not v["pkg"]]
print("count",len(z))
for m in sorted(z,key=lambda x:-out[x]["lines"]):
    v=out[m]
    print(f"Z|{m}|{v['lines']}L|{v['date']}|refs={len(v['refs'])}{v['cats']}|str={v['strmention']}|main={v['main']}|{v['doc'][:60]}")
print("\n== ZERO IMPORTERS AND ZERO REFS ==")
zz=[m for m in z if not out[m]["refs"]]
print(len(zz),"| lines",sum(out[m]["lines"] for m in zz))
for m in zz: print(f"  {m}|{out[m]['path']}|{out[m]['lines']}L|{out[m]['date']}|str={out[m]['strmention']}|main={out[m]['main']}")
print("\n== TEST-ONLY MODULES (all refs are tests) ==")
to=[m for m,v in out.items() if v["imp"]==0 and v["refs"] and set(v["cats"])=={"tests"}]
print(len(to))
for m in sorted(to,key=lambda x:-out[x]["lines"])[:20]: print(f"  {m}|{out[m]['lines']}L|{out[m]['date']}|tests={len(out[m]['refs'])}")
print("\n== TEST/SCRIPT-DEFINED HELPERS ALSO IN SRC (real overlap) ==")
srcf={}
for m,d in D.items():
    for f in d["defs"]:
        nm=f.split("(")[0].replace("async ","").replace("class ","")
        srcf.setdefault(nm,[]).append(m)
rows=[]
for dp,dns,fns in os.walk("tests"):
    dns[:]=[d for d in dns if d not in SKIP]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p=os.path.join(dp,fn)
        txt=open(p,encoding="utf-8",errors="replace").read()
        try: t=ast.parse(txt)
        except Exception: continue
        imported=set()
        for n in ast.walk(t):
            if isinstance(n,ast.ImportFrom):
                for a in n.names: imported.add(a.asname or a.name)
        for n in t.body:
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                if n.name in srcf and n.name not in imported and len(n.body)>1:
                    rows.append((n.name,p,srcf[n.name][0],len(n.body)))
for r in sorted(rows,key=lambda x:x[0]): print(f"H|{r[0]}|{r[1]}|src={r[2]}|bodylines={r[3]}")
PY

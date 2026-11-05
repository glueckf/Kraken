import json, os, subprocess, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reef_topologies as rt
src = {
 "medium_b": (rt._MEDIUM_B_EDGES, rt._MEDIUM_B_LEAVES, rt._MEDIUM_B_CP),
 "medium_c": (rt._MEDIUM_C_EDGES, rt._MEDIUM_C_LEAVES, rt._MEDIUM_C_CP),
 "medium_d": (rt._MEDIUM_D_EDGES, rt._MEDIUM_D_LEAVES, rt._MEDIUM_D_CP),
 "medium_e": (rt._MEDIUM_E_EDGES, rt._MEDIUM_E_LEAVES, rt._MEDIUM_E_CP),
 "large": (rt._LARGE_EDGES, rt._LARGE_LEAVES, rt._LARGE_CP),
 "large_b": (rt._LARGE_B_EDGES, rt._LARGE_B_LEAVES, rt._LARGE_B_CP),
 "large_c": (rt._LARGE_B_EDGES, rt._LARGE_C_LEAVES, rt._LARGE_B_CP),
 "large_d": (rt._LARGE_D_EDGES, rt._LARGE_D_LEAVES, rt._LARGE_D_CP),
}
out = open("anchors.jsonl", "w")
for tid, (e, l, cp) in src.items():
    spec = dict(edges=e, leaves=l, cp={k: (None if v == math.inf else v) for k, v in cp.items()})
    json.dump(spec, open(f"junk/{tid}.json", "w"))
    r = subprocess.run([sys.executable, "../lab_worker.py", f"{tid}.json"],
                       capture_output=True, text=True, cwd="junk")
    res = json.loads([x for x in r.stdout.splitlines() if x.startswith("{")][-1])
    out.write(json.dumps(dict(id=tid, spec=spec, per_query=res["per_query"], fails=res["fails"], sol=res["sol"])) + "\n")
    print(tid, len(res["fails"]), "fails")

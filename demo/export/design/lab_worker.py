"""Evaluate one candidate spec (JSON on argv[1] path) in a fresh process; print JSON."""
import os, sys, json
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io, contextlib
import topology_lab as lab
lab.MAX_ENUM = 20_000

spec = json.load(open(sys.argv[1]))
spec["edges"] = {int(k): v for k, v in spec["edges"].items()}
spec["leaves"] = {int(k): v for k, v in spec["leaves"].items()}
spec["cp"] = {int(k): (float("inf") if v is None else v) for k, v in spec["cp"].items()}
try:
    with contextlib.redirect_stdout(io.StringIO()):
        per_query, scs = lab.evaluate("cand", spec)
    sol = {sid: [dict(nodes=sorted(set(s["placement"].values())), placement=s["placement"], comm=s["comm"],
                      cost=s["cost"], lat=s["latency"]) for s in sc["kraken_stages"]] for sid, sc in scs.items()}
    print(json.dumps(dict(ok=True, per_query=per_query, fails=lab.verdict(per_query), sol=sol)))
except Exception as e:
    print(json.dumps(dict(ok=False, error=repr(e))))

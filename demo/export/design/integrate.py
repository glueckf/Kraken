"""Put pool.json (select_pool.py output) into the demo as designed topologies.

Regenerates the BEGIN/END designed blocks in reef_topologies.py and
topologies.py, re-exports only topologies whose spec changed (child mode, one
fresh process each), rebuilds manifest.json and dist/. Names stick to a spec
across runs. Legacy picks (lagoon, mangroves) only fill up to MIN_SHOWN.
"""
import hashlib, json, os, re, shutil, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(SCR)
WEB = os.path.join(os.path.dirname(EXP), "web")
PY = sys.executable
STATE = os.path.join(SCR, "designed_state.json")
CURATED = ["forge", "medium", "medium_b", "medium_c", "medium_d", "medium_e", "large", "large_b", "large_c", "large_d"]
MIN_SHOWN = 3
VISIBLE = ["seq_abc", "seq_abcd", "seq_abcde", "and_nested"]
NAMES = [("atoll", "Atoll", "Atoll"), ("delta", "Delta", "Delta"), ("fjord", "Fjord", "Fjord"),
         ("kelp", "Kelp Forest", "Kelpwald"), ("estuary", "Estuary", "Mündung"), ("seamount", "Seamount", "Tiefseeberg"),
         ("shoal", "Shoal", "Sandbank"), ("bay", "Bay", "Bucht"), ("strait", "Strait", "Meerenge"),
         ("cove", "Cove", "Grotte"), ("tidepool", "Tide Pool", "Priel"), ("trench", "Trench", "Graben"),
         ("cape", "Cape", "Kap"), ("isle", "Isle", "Insel"), ("harbor", "Harbor", "Hafen"), ("gulf", "Gulf", "Golf"),
         ("sound", "Sound", "Sund"), ("dunes", "Dunes", "Dünen"), ("cliffs", "Cliffs", "Klippen"), ("reefflat", "Reef Flat", "Riffdach")]
LEGACY = {"lagoon": ("Lagoon", "Lagune", ["seq_abc", "seq_abcd", "seq_abcde"]),
          "mangroves": ("Mangroves", "Mangroven", ["seq_abc", "seq_abcd", "seq_abcde", "and_nested"])}


def norm(spec):
    return dict(edges={int(k): sorted(v) for k, v in spec["edges"].items()},
                leaves={int(k): sorted(v) for k, v in spec["leaves"].items()},
                cp={int(k): v for k, v in spec["cp"].items()})


def key(spec):
    return hashlib.sha1(json.dumps(norm(spec), sort_keys=True).encode()).hexdigest()[:12]


def n_nodes(spec):
    s = norm(spec)
    return max(max(s["edges"]), *(max(c) for c in s["edges"].values())) + 1


def main():
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"names": {}, "exported": {}, "legacy": {}}
    if not st["legacy"]:
        sys.path.insert(0, EXP)
        import reef_topologies as rt
        for lid in LEGACY:
            u = lid.upper()
            st["legacy"][lid] = dict(edges=getattr(rt, f"_{u}_EDGES"), leaves=getattr(rt, f"_{u}_LEAVES"),
                                     cp={k: (None if v == float("inf") else v) for k, v in getattr(rt, f"_{u}_CP").items()})
    entries = []
    for r in json.load(open(os.path.join(SCR, "pool.json"))):
        h = key(r["spec"])
        if h not in st["names"]:
            used = set(st["names"].values())
            st["names"][h] = next(nid for nid, _, _ in NAMES if nid not in used)
        nid = st["names"][h]
        _, lab, lab_de = next(x for x in NAMES if x[0] == nid)
        scen = [s for s in VISIBLE if s in r["per_query"] and 2 <= r["per_query"][s]["subq"] <= 5]
        entries.append(dict(id=nid, label=lab, label_de=lab_de, spec=norm(r["spec"]), scenarios=scen, hash=h))
    for lid, (lab, lab_de, scen) in LEGACY.items():
        if len(entries) >= MIN_SHOWN:
            break
        spec = st["legacy"][lid]
        entries.append(dict(id=lid, label=lab, label_de=lab_de, spec=norm(spec), scenarios=scen, hash=key(spec)))
    entries.sort(key=lambda e: n_nodes(e["spec"]))

    # ---- code generation
    code = ["# BEGIN designed (generated -- regenerate, don't hand-edit)"]
    for e in entries:
        u, s = e["id"].upper(), e["spec"]
        cp = ", ".join(f"{k}: {'math.inf' if v is None else v}" for k, v in sorted(s["cp"].items()))
        code += [f"_{u}_EDGES = {s['edges']}", f"_{u}_LEAVES = {s['leaves']}", f"_{u}_CP = {{{cp}}}",
                 f"build_{e['id']} = _build(_{u}_EDGES, _{u}_LEAVES, _{u}_CP)", ""]
    code += ["_DESIGNED = {"] + [f'    "{e["id"]}": build_{e["id"]},' for e in entries] + ["}", "# END designed"]
    p = os.path.join(EXP, "reef_topologies.py")
    src = open(p).read()
    src = re.sub(r"# BEGIN designed.*?# END designed", lambda _: "\n".join(code), src, flags=re.S)
    open(p, "w").write(src)
    topo = ["    # BEGIN designed (generated)"]
    for e in entries:
        topo += [f'    dict(id="{e["id"]}", family="{e["id"]}", label="{e["label"]}", label_de="{e["label_de"]}",',
                 f'         network_size={n_nodes(e["spec"])}, seed=None, kind="hand_curated",',
                 f'         scenarios={e["scenarios"]}),']
    topo.append("    # END designed")
    p = os.path.join(EXP, "topologies.py")
    src = open(p).read()
    src = re.sub(r"    # BEGIN designed.*?    # END designed", lambda _: "\n".join(topo), src, flags=re.S)
    open(p, "w").write(src)

    # ---- export changed ones
    out = os.path.join(WEB, "scenarios")
    man = json.load(open(os.path.join(out, "manifest.json")))
    old = {t["id"]: t for t in man["topologies"]}
    frags = {}
    for e in entries:
        if st["exported"].get(e["id"]) == e["hash"] and e["id"] in old and os.path.isdir(os.path.join(out, e["id"])):
            frags[e["id"]] = old[e["id"]]
            continue
        print(f"exporting {e['id']} ({n_nodes(e['spec'])} nodes) ...", flush=True)
        r = subprocess.run([PY, "export_scenario.py", e["id"]], cwd=EXP, capture_output=True, text=True)
        bad = [l for l in (r.stdout + r.stderr).splitlines() if "mismatch" in l.lower() or "error" in l.lower()]
        fp = os.path.join(out, f".manifest-{e['id']}.json")
        if r.returncode != 0 or not os.path.exists(fp):
            print(f"  !! export failed (exit {r.returncode})\n" + "\n".join((r.stdout + r.stderr).splitlines()[-15:]))
            sys.exit(1)
        if bad:
            print("  !! " + "\n  !! ".join(bad[:10]))
        frags[e["id"]] = json.load(open(fp))
        os.remove(fp)
        st["exported"][e["id"]] = e["hash"]
    keep = {e["id"] for e in entries}
    for tid in old:
        if tid not in CURATED and tid not in keep:
            shutil.rmtree(os.path.join(out, tid), ignore_errors=True)
            st["exported"].pop(tid, None)
            print(f"removed {tid}")
    man["topologies"] = [old[c] for c in CURATED if c in old] + [frags[e["id"]] for e in entries]
    json.dump(man, open(os.path.join(out, "manifest.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(st, open(STATE, "w"), indent=1)
    r = subprocess.run(["npm", "run", "build"], cwd=WEB, capture_output=True, text=True)
    print("build:", "ok" if r.returncode == 0 else r.stdout[-500:] + r.stderr[-500:])
    for e in entries:
        print(f"  {e['id']:10s} {n_nodes(e['spec']):2d}n  {e['label_de']:12s} {e['scenarios']}")


if __name__ == "__main__":
    main()

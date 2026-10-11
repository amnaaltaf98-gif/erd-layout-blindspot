#!/usr/bin/env python3
import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from itertools import combinations

import networkx as nx
import pandas as pd
from shapely.geometry import LineString, box

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
SEED = 42
SIZES = [5, 8, 12, 16]
PER_SIZE = 10
REPAIR_ROUNDS = 3
TABLE_W = 200
MAX_NEW_TOKENS = 1500
MAX_ISSUES_IN_FEEDBACK = 15
RANDOM_REPS = 5

CANVAS_W = None  
CANVAS_H = None

TABLE_NAMES = [
    "users", "orders", "products", "customers", "suppliers", "categories",
    "payments", "invoices", "shipments", "employees", "departments", "reviews",
    "addresses", "carts", "inventory", "warehouses", "courses", "students",
    "teachers", "enrollments", "appointments", "doctors", "patients",
    "branches", "accounts", "transactions", "tickets", "events", "venues",
    "projects",
]
COLUMN_POOL = [
    "name", "email", "created_at", "status", "price", "quantity",
    "description", "phone", "date", "amount", "title", "notes",
]

SYSTEM_PROMPT = ("You are a diagram layout engine. You output only valid JSON, "
                 "with no explanation and no markdown.")
REPAIR_MSG = "Make sure the lines are not overlapping. Return the full JSON."

def table_height(n_cols):
    return 30 + 20 * n_cols


def balanced_valid(d):
    """Rows of the schemas that have a valid layout in every round present.
    Averages over these are comparable between rounds (the set of schemas does
    not change from round to round)."""
    nr = d["round"].nunique()
    ok = d[d["valid"]].groupby("schema")["round"].nunique()
    keep = ok[ok == nr].index
    return d[d["valid"] & d["schema"].isin(keep)]


def save_json(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def path_in(workdir, name):
    return os.path.join(workdir, name)

def make_schema(rng, n_tables, schema_id):
    names = rng.sample(TABLE_NAMES, n_tables)

    # Random spanning tree so the graph is always connected
    fks = set()
    for i in range(1, n_tables):
        parent = rng.randrange(0, i)
        fks.add((names[i], names[parent]))

    # Extra foreign keys so the graph has cycles
    extra = round(0.4 * n_tables)
    attempts = 0
    while extra > 0 and attempts < 200:
        attempts += 1
        a, b = rng.sample(names, 2)
        if (a, b) in fks or (b, a) in fks:
            continue
        fks.add((a, b))
        extra -= 1

    tables = []
    for name in names:
        cols = ["id"] + rng.sample(COLUMN_POOL, rng.randint(2, 4))
        for child, parent in sorted(fks):
            if child == name:
                cols.append(f"{parent}_id")
        tables.append({"name": name, "columns": cols})

    return {
        "id": schema_id,
        "n_tables": n_tables,
        "tables": tables,
        "foreign_keys": [{"from": a, "to": b} for a, b in sorted(fks)],
    }


def is_connected(schema):
    g = nx.Graph()
    g.add_nodes_from(t["name"] for t in schema["tables"])
    g.add_edges_from((e["from"], e["to"]) for e in schema["foreign_keys"])
    return nx.is_connected(g)


def add_sizes(schemas):
    for s in schemas:
        for t in s["tables"]:
            t["w"] = TABLE_W
            t["h"] = table_height(len(t["columns"]))
    return schemas


def extent(pos, schema):
    size = {t["name"]: (t["w"], t["h"]) for t in schema["tables"]}
    return (max(x + size[n][0] for n, (x, y) in pos.items()),
            max(y + size[n][1] for n, (x, y) in pos.items()))


def stage_schemas(workdir):
    global CANVAS_W, CANVAS_H
    sp = path_in(workdir, "schemas.json")
    if os.path.exists(sp):
        schemas = json.load(open(sp))
        print(f"[schemas] loaded {len(schemas)} schemas")
    else:
        rng = random.Random(SEED)
        schemas = []
        for n in SIZES:
            for k in range(PER_SIZE):
                schemas.append(make_schema(rng, n, f"s{n}_{k}"))
        assert all(is_connected(s) for s in schemas)
        print(f"[schemas] built {len(schemas)} schemas")
    schemas = add_sizes(schemas)
    save_json(schemas, sp)

    for n in SIZES:
        group = [s for s in schemas if s["n_tables"] == n]
        avg_fk = sum(len(s["foreign_keys"]) for s in group) / len(group)
        print(f"  {n} tables: {len(group)} schemas, {avg_fk:.1f} foreign keys on average")

    cp = path_in(workdir, "config.json")
    cfg = load_json(cp, {})
    if "canvas_w" not in cfg:
        ext = [extent(graphviz_layout(s, "neato"), s) for s in schemas]
        cfg["canvas_w"] = int(math.ceil((max(e[0] for e in ext) + 20) / 100) * 100)
        cfg["canvas_h"] = int(math.ceil((max(e[1] for e in ext) + 20) / 100) * 100)
        cfg["model_id"] = MODEL_ID
        cfg["seed"] = SEED
        save_json(cfg, cp)
    CANVAS_W, CANVAS_H = cfg["canvas_w"], cfg["canvas_h"]
    print(f"[schemas] canvas {CANVAS_W} x {CANVAS_H}")
    return schemas


def graphviz_layout(schema, engine="neato", margin=20):
    lines = ["graph G {", "  node [shape=box, fixedsize=true];"]
    if engine == "neato":
        lines.append('  overlap=false; sep="+20"; splines=false;')
    else:
        lines.append("  nodesep=0.6; ranksep=0.8;")
    for t in schema["tables"]:
        lines.append(f'  {t["name"]} [width={t["w"] / 72:.4f}, height={t["h"] / 72:.4f}];')
    for e in schema["foreign_keys"]:
        lines.append(f'  {e["from"]} -- {e["to"]};')
    lines.append("}")
    try:
        out = subprocess.run([engine, "-Tplain"], input="\n".join(lines),
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        sys.exit("Graphviz is not installed. Run: apt-get install -y graphviz")

    graph_h, nodes = None, {}
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "graph":
            graph_h = float(parts[3])
        elif parts[0] == "node":
            nodes[parts[1]] = tuple(map(float, parts[2:6]))
    pos = {}
    for name, (x, y, w, h) in nodes.items():
        cx, cy = x * 72, (graph_h - y) * 72          # flip y, origin top left
        pos[name] = (cx - w * 36 + margin, cy - h * 36 + margin)
    return pos


def random_layout(schema, rng):
    return {t["name"]: (rng.uniform(0, CANVAS_W - t["w"]),
                        rng.uniform(0, CANVAS_H - t["h"]))
            for t in schema["tables"]}


def find_issues(pos, schema):
    """Lists every problem in a layout. Edges are straight lines between
    table centers."""
    size = {t["name"]: (t["w"], t["h"]) for t in schema["tables"]}
    rects = {n: box(x, y, x + size[n][0], y + size[n][1]) for n, (x, y) in pos.items()}
    centers = {n: r.centroid for n, r in rects.items()}
    edges = [(e["from"], e["to"]) for e in schema["foreign_keys"]]
    lines = {e: LineString([centers[e[0]], centers[e[1]]]) for e in edges}

    overlaps = [(a, b) for a, b in combinations(rects, 2)
                if rects[a].intersection(rects[b]).area > 1]
    crossings = [(e1, e2) for e1, e2 in combinations(edges, 2)
                 if not (set(e1) & set(e2)) and lines[e1].intersects(lines[e2])]
    through = [(e, n) for e in edges for n, r in rects.items()
               if n not in e and lines[e].intersects(r)]
    oob = [n for n, (x, y) in pos.items()
           if x < 0 or y < 0 or x + size[n][0] > CANVAS_W or y + size[n][1] > CANVAS_H]
    return {"overlaps": overlaps, "crossings": crossings,
            "through": through, "out_of_bounds": oob}


def score_layout(pos, schema):
    iss = find_issues(pos, schema)
    sc = {k: len(v) for k, v in iss.items()}
    sc["total"] = sc["overlaps"] + sc["crossings"] + sc["through"]
    return sc

def build_prompt(schema):
    tables_txt = "\n".join(f'- {t["name"]} (width {t["w"]}, height {t["h"]})'
                           for t in schema["tables"])
    fk_txt = "\n".join(f'- {e["from"]} -> {e["to"]}' for e in schema["foreign_keys"])
    return f"""Place the tables of an entity relationship diagram on a canvas that is {CANVAS_W} wide and {CANVAS_H} high. The origin (0, 0) is the top left corner. Each (x, y) is the top left corner of a table.

Tables:
{tables_txt}

Relationships (each is drawn as a straight line between the centers of the two tables):
{fk_txt}

Place every table inside the canvas. Return only JSON in this exact format:
{{"tables": [{{"name": "table_name", "x": 0, "y": 0}}]}}"""


def parse_layout(text, schema):
    """Returns (positions or None, error string or None)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None, "no_json"
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None, "invalid_json"
    try:
        pos = {t["name"]: (float(t["x"]), float(t["y"])) for t in data["tables"]}
    except (KeyError, TypeError, ValueError):
        return None, "bad_structure"
    if set(pos) != {t["name"] for t in schema["tables"]}:
        return None, "wrong_tables"
    return pos, None


def feedback_message(prev_text, schema):
    """Control condition: tell the model exactly what is wrong."""
    pos, err = parse_layout(prev_text, schema)
    if pos is None:
        return ("Your last answer was not valid JSON in the requested format. "
                "Return the full layout as JSON only.")
    iss = find_issues(pos, schema)
    items = []
    for a, b in iss["overlaps"]:
        items.append(f"Table {a} overlaps table {b}.")
    for e1, e2 in iss["crossings"]:
        items.append(f"The line {e1[0]} -> {e1[1]} crosses the line {e2[0]} -> {e2[1]}.")
    for e, n in iss["through"]:
        items.append(f"The line {e[0]} -> {e[1]} passes through table {n}.")
    for n in iss["out_of_bounds"]:
        items.append(f"Table {n} is outside the canvas.")
    if not items:
        return "No problems were detected. Return the same JSON."
    shown = items[:MAX_ISSUES_IN_FEEDBACK]
    more = len(items) - len(shown)
    txt = "\n".join(f"- {i}" for i in shown)
    if more > 0:
        txt += f"\n- ...and {more} more problems."
    return ("These problems were found in your layout:\n" + txt +
            "\nMove tables to fix them. Return the full JSON.")


def lazy_generator(mock):
    state = {}

    def gen(messages, max_new_tokens=MAX_NEW_TOKENS):
        if "g" not in state:
            state["g"] = make_generator(mock)
        return state["g"](messages, max_new_tokens)
    return gen


def make_generator(mock):
    if mock:
        import re

        def mock_generate(messages, max_new_tokens=MAX_NEW_TOKENS):
            names = re.findall(r"^- (\w+) \(width", messages[1]["content"], flags=re.M)
            rng = random.Random(len(messages) * 1000 + len(messages[1]["content"]))
            tables = [{"name": n, "x": rng.randrange(0, CANVAS_W - TABLE_W),
                       "y": rng.randrange(0, CANVAS_H - 200)} for n in names]
            return json.dumps({"tables": tables})
        return mock_generate

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if not torch.cuda.is_available():
        print("WARNING: no GPU found. Switch the runtime to a T4 GPU.")
    print(f"[model] loading {MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    try:
        llm = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, dtype=torch.float16, device_map="auto")
    except TypeError:
        llm = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, torch_dtype=torch.float16, device_map="auto")
    llm.eval()

    def generate(messages, max_new_tokens=MAX_NEW_TOKENS):
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(llm.device)
        with torch.no_grad():
            out = llm.generate(**inputs, max_new_tokens=max_new_tokens,
                               do_sample=False, temperature=None, top_p=None,
                               top_k=None, pad_token_id=tokenizer.eos_token_id)
        return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True)
    return generate


def subset(schemas, limit):
    if not limit:
        return schemas
    return [s for s in schemas if int(s["id"].split("_")[1]) < limit]


def stage_round0(workdir, schemas, gen):
    path = path_in(workdir, "round0_raw.json")
    raw = load_json(path, {})
    t0 = time.time()
    todo = [s for s in schemas if s["id"] not in raw]
    print(f"[round0] {len(todo)} to generate, {len(schemas) - len(todo)} already saved")
    for i, s in enumerate(todo, 1):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(s)}]
        raw[s["id"]] = gen(messages)
        save_json(raw, path)
        print(f"  {s['id']} ({i}/{len(todo)}) {time.time() - t0:.0f}s")
    return raw


def stage_followups(workdir, schemas, gen, round0, store_name, prefix,
                    followup_fn, label, rounds):
    path = path_in(workdir, store_name)
    store = load_json(path, {})
    t0 = time.time()
    print(f"[{label}] {len(store)} outputs already saved")
    for s in schemas:
        if s["id"] not in round0:
            continue
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(s)}]
        prev = round0[s["id"]]
        for k in range(1, rounds + 1):
            key = f"{s['id']}_{prefix}{k}"
            messages = messages + [
                {"role": "assistant", "content": prev},
                {"role": "user", "content": followup_fn(prev, s)},
            ]
            if key not in store:
                store[key] = gen(messages)
                save_json(store, path)
                print(f"  {key} {time.time() - t0:.0f}s")
            prev = store[key]
    return store


def draw_layout(ax, pos, schema, title):
    ax.set_xlim(0, CANVAS_W)
    ax.set_ylim(CANVAS_H, 0)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    if pos is None:
        ax.set_title(title + " (invalid)", fontsize=9)
        return
    size = {t["name"]: (t["w"], t["h"]) for t in schema["tables"]}
    from matplotlib.patches import Rectangle
    centers = {}
    for n, (x, y) in pos.items():
        w, h = size[n]
        ax.add_patch(Rectangle((x, y), w, h, fill=True, alpha=0.5,
                               edgecolor="black", facecolor="#9ecae1"))
        ax.text(x + w / 2, y + h / 2, n, ha="center", va="center", fontsize=6)
        centers[n] = (x + w / 2, y + h / 2)
    for e in schema["foreign_keys"]:
        (x1, y1), (x2, y2) = centers[e["from"]], centers[e["to"]]
        ax.plot([x1, x2], [y1, y2], color="crimson", linewidth=0.8)
    sc = score_layout(pos, schema)
    ax.set_title(f"{title} (problems: {sc['total']})", fontsize=9)


def stage_analyse(workdir, schemas, round0, repair, feedback, rounds):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figdir = path_in(workdir, "figures")
    os.makedirs(figdir, exist_ok=True)
    n_edges = {s["id"]: len(s["foreign_keys"]) for s in schemas}

    # ---- baselines
    rows = []
    for s in schemas:
        for engine in ["neato", "dot"]:
            sc = score_layout(graphviz_layout(s, engine), s)
            rows.append({"schema": s["id"], "n_tables": s["n_tables"],
                         "method": f"graphviz_{engine}", **sc})
        for rep in range(RANDOM_REPS):
            rng = random.Random(f"{SEED}-{s['id']}-{rep}")
            sc = score_layout(random_layout(s, rng), s)
            rows.append({"schema": s["id"], "n_tables": s["n_tables"],
                         "method": "random", **sc})
    base = pd.DataFrame(rows)
    base["per_edge"] = base.apply(lambda r: r.total / n_edges[r.schema], axis=1)
    base.to_csv(path_in(workdir, "baseline_scores.csv"), index=False)

    # ---- model rows
    def model_row(cond, s, k, text):
        pos, err = parse_layout(text, s)
        row = {"condition": cond, "schema": s["id"], "n_tables": s["n_tables"],
               "round": k, "valid": err is None, "error": err}
        if pos is not None:
            row.update(score_layout(pos, s))
            row["per_edge"] = row["total"] / n_edges[s["id"]]
            row["distinct_x"] = len({round(x) for x, y in pos.values()})
            row["distinct_y"] = len({round(y) for x, y in pos.values()})
        return row

    rows = []
    for s in schemas:
        if s["id"] not in round0:
            continue
        for cond, store, prefix in [("plain", repair, "r"), ("feedback", feedback, "fb")]:
            rows.append(model_row(cond, s, 0, round0[s["id"]]))
            for k in range(1, rounds + 1):
                text = store.get(f"{s['id']}_{prefix}{k}")
                if text is not None:
                    rows.append(model_row(cond, s, k, text))
    df = pd.DataFrame(rows)
    df.to_csv(path_in(workdir, "model_scores.csv"), index=False)

    cols = ["overlaps", "crossings", "through", "out_of_bounds", "total"]
    out = []

    def section(title, table):
        out.append(f"## {title}\n\n```\n{table}\n```\n")

    r0 = df[(df.condition == "plain") & (df["round"] == 0)]
    section("Round 0: share of valid JSON layouts, by size",
            r0.groupby("n_tables")["valid"].mean().round(2).to_string())
    section("Round 0: failure types",
            r0[~r0.valid].groupby(["n_tables", "error"]).size().to_string()
            if (~r0.valid).any() else "none")

    comp = pd.DataFrame({
        "graphviz_neato": base[base.method == "graphviz_neato"].groupby("n_tables")["total"].mean(),
        "graphviz_dot": base[base.method == "graphviz_dot"].groupby("n_tables")["total"].mean(),
        "random": base[base.method == "random"].groupby("n_tables")["total"].mean(),
        "qwen_round0": r0[r0.valid].groupby("n_tables")["total"].mean(),
    }).round(2)
    section("Average layout problems (overlaps + crossings + lines through tables)",
            comp.to_string())

    comp_pe = pd.DataFrame({
        "graphviz_neato": base[base.method == "graphviz_neato"].groupby("n_tables")["per_edge"].mean(),
        "random": base[base.method == "random"].groupby("n_tables")["per_edge"].mean(),
        "qwen_round0": r0[r0.valid].groupby("n_tables")["per_edge"].mean(),
    }).round(2)
    section("Problems per foreign key", comp_pe.to_string())
    section("Round 0 problem breakdown for Qwen, by size",
            r0[r0.valid].groupby("n_tables")[cols].mean().round(2).to_string())
    section("Round 0 spread of positions (distinct x and y values)",
            r0[r0.valid].groupby("n_tables")[["distinct_x", "distinct_y"]].mean().round(1).to_string())

    for cond in ["plain", "feedback"]:
        d = balanced_valid(df[df.condition == cond])
        section(f"Average problems by round, condition: {cond} (schemas valid in every round)",
                d.groupby(["n_tables", "round"])["total"].mean().unstack().round(1).to_string())
        allr = df[df.condition == cond]
        section(f"Share of valid JSON by round, condition: {cond}",
                allr.groupby(["n_tables", "round"])["valid"].mean().unstack().round(2).to_string())

    reg = []
    for cond in ["plain", "feedback"]:
        piv = df[(df.condition == cond) & df.valid].pivot(
            index="schema", columns="round", values="total")
        for k in range(1, rounds + 1):
            if k not in piv.columns or (k - 1) not in piv.columns:
                continue
            both = piv[[k - 1, k]].dropna()
            if both.empty:
                continue
            d = both[k] - both[k - 1]
            reg.append({"condition": cond, "round": k, "n": len(d),
                        "worse_%": round((d > 0).mean() * 100, 1),
                        "same_%": round((d == 0).mean() * 100, 1),
                        "better_%": round((d < 0).mean() * 100, 1),
                        "mean_change": round(d.mean(), 2)})
        if rounds in piv.columns and 0 in piv.columns:
            both = piv[[0, rounds]].dropna()
            if not both.empty:
                reg.append({"condition": cond, "round": f"0 to {rounds}", "n": len(both),
                            "worse_%": round((both[rounds] > both[0]).mean() * 100, 1),
                            "same_%": round((both[rounds] == both[0]).mean() * 100, 1),
                            "better_%": round((both[rounds] < both[0]).mean() * 100, 1),
                            "mean_change": round((both[rounds] - both[0]).mean(), 2)})
    regdf = pd.DataFrame(reg)
    regdf.to_csv(path_in(workdir, "regression_rates.csv"), index=False)
    section("Repair regression: did a round make the layout worse?",
            regdf.to_string(index=False) if len(regdf) else "no data")

    # ---- plots
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, col, ylabel in [(axes[0], "total", "Average problems"),
                            (axes[1], "per_edge", "Problems per foreign key")]:
        src = base[base.method == "graphviz_neato"].groupby("n_tables")[col].mean()
        ax.plot(src.index, src.values, marker="o", label="Graphviz neato")
        src = base[base.method == "random"].groupby("n_tables")[col].mean()
        ax.plot(src.index, src.values, marker="o", linestyle="--", label="Random placement")
        src = r0[r0.valid].groupby("n_tables")[col].mean()
        ax.plot(src.index, src.values, marker="o", label="Qwen2.5-3B round 0")
        ax.set_xlabel("Number of tables")
        ax.set_ylabel(ylabel)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path_in(figdir, "round0_vs_baselines.png"), dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, len(SIZES), figsize=(14, 3.6), sharey=False)
    for ax, n in zip(axes, SIZES):
        for cond, style in [("plain", "-"), ("feedback", "--")]:
            bal = balanced_valid(df[df.condition == cond])
            d = bal[bal.n_tables == n]
            m = d.groupby("round")["total"].mean()
            ax.plot(m.index, m.values, marker="o", linestyle=style,
                    label="'don't overlap' prompt" if cond == "plain" else "computed feedback")
        ref = base[(base.method == "graphviz_neato") & (base.n_tables == n)]["total"].mean()
        ax.axhline(ref, color="gray", linestyle=":", label="Graphviz neato")
        ax.set_title(f"{n} tables")
        ax.set_xlabel("Repair round")
        ax.set_xticks(range(rounds + 1))
    axes[0].set_ylabel("Average problems")
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path_in(figdir, "repair_trajectories.png"), dpi=150)
    plt.close(fig)

    # ---- example images: neato, round 0, last plain repair round
    for sid in ["s5_0", "s8_0", "s12_0", "s16_0"]:
        s = next((x for x in schemas if x["id"] == sid), None)
        if s is None or sid not in round0:
            continue
        panels = [("Graphviz neato", graphviz_layout(s, "neato")),
                  ("Qwen round 0", parse_layout(round0[sid], s)[0])]
        for k in range(1, rounds + 1):
            text = repair.get(f"{sid}_r{k}")
            if text is not None:
                panels.append((f"Qwen after repair {k}", parse_layout(text, s)[0]))
        fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 3.6))
        axes = [axes] if len(panels) == 1 else axes
        for ax, (title, pos) in zip(axes, panels):
            draw_layout(ax, pos, s, title)
        fig.tight_layout()
        fig.savefig(path_in(figdir, f"example_{sid}.png"), dpi=130)
        plt.close(fig)

    summary = ("# Results summary (auto generated)\n\n"
               f"Model: {MODEL_ID}, greedy decoding. Canvas {CANVAS_W} x {CANVAS_H}. "
               f"{len(schemas)} schemas.\n\n" + "\n".join(out))
    with open(path_in(workdir, "results_summary.md"), "w") as f:
        f.write(summary)
    print(summary)
    print(f"\nSaved tables, plots and examples in {workdir}")



PLACEHOLDER = "PASTE YOUR ANSWER HERE"
MIN_ANSWER_CHARS = 200


def read_answers(workdir):
    p = path_in(workdir, "my_answers.md")
    if not os.path.exists(p):
        return None
    parts, cur = {}, None
    for line in open(p, encoding="utf-8").read().splitlines():
        m = re.match(r"^##\s+(Q1|OBSERVATIONS|Q3)\s*$", line.strip())
        if m:
            cur = m.group(1)
            parts[cur] = []
        elif cur:
            parts[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in parts.items()}


def answer_problems(ans):
    if ans is None:
        return ["my_answers.md was not found. Run the 'My answers' cell first."]
    problems = []
    for key, label in [("Q1", "Question 1 (the blind spot)"),
                       ("Q3", "Question 3 (path forward)")]:
        v = ans.get(key, "")
        if PLACEHOLDER in v or len(v) < MIN_ANSWER_CHARS:
            problems.append(f"{label} is empty, still has the placeholder, or is "
                            f"shorter than {MIN_ANSWER_CHARS} characters.")
    return problems


def md_table(df, index=True):
    cols = ([df.index.name or ""] if index else []) + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for idx, row in df.iterrows():
        cells = ([str(idx)] if index else []) + ["" if pd.isna(v) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def stage_readme(workdir):
    ans = read_answers(workdir)
    problems = answer_problems(ans)
    if problems:
        sys.exit("Cannot build the README yet:\n  - " + "\n  - ".join(problems))

    cfg = load_json(path_in(workdir, "config.json"), {})
    ms = pd.read_csv(path_in(workdir, "model_scores.csv"))
    base = pd.read_csv(path_in(workdir, "baseline_scores.csv"))
    reg = pd.read_csv(path_in(workdir, "regression_rates.csv"), dtype=str) \
        if os.path.exists(path_in(workdir, "regression_rates.csv")) else pd.DataFrame()
    ms["valid"] = ms["valid"].astype(bool)
    rounds = int(ms["round"].max())
    r0 = ms[(ms.condition == "plain") & (ms["round"] == 0)]
    n_schemas = r0["schema"].nunique()
    sizes = sorted(r0["n_tables"].unique())

    comp = pd.DataFrame({
        "Graphviz neato": base[base.method == "graphviz_neato"].groupby("n_tables")["total"].mean(),
        "Random placement": base[base.method == "random"].groupby("n_tables")["total"].mean(),
        "Qwen2.5-3B round 0": r0[r0.valid].groupby("n_tables")["total"].mean(),
    }).round(2)
    comp.index.name = "tables"
    comp_pe = pd.DataFrame({
        "Graphviz neato": base[base.method == "graphviz_neato"].groupby("n_tables")["per_edge"].mean(),
        "Random placement": base[base.method == "random"].groupby("n_tables")["per_edge"].mean(),
        "Qwen2.5-3B round 0": r0[r0.valid].groupby("n_tables")["per_edge"].mean(),
    }).round(2)
    comp_pe.index.name = "tables"
    validity = r0.groupby("n_tables")["valid"].agg(["sum", "count"])
    validity["share valid"] = (validity["sum"] / validity["count"]).round(2)
    validity = validity.rename(columns={"sum": "valid layouts", "count": "schemas"})
    for c in ["valid layouts", "schemas"]:
        validity[c] = validity[c].astype(int).astype(str)   # keep whole numbers whole
    validity.index.name = "tables"
    breakdown = r0[r0.valid].groupby("n_tables")[
        ["overlaps", "crossings", "through", "out_of_bounds"]].mean().round(2)
    breakdown.index.name = "tables"
    breakdown = breakdown.rename(columns={
        "overlaps": "table overlaps", "crossings": "line crossings",
        "through": "lines through tables", "out_of_bounds": "tables off canvas"})

    traj, traj_n = {}, {}
    for cond in ["plain", "feedback"]:
        d = balanced_valid(ms[ms.condition == cond])
        if (d["round"] > 0).any():
            t = d.groupby(["n_tables", "round"])["total"].mean().unstack().round(1)
            t.index.name = "tables"
            t.columns = [f"round {c}" for c in t.columns]
            traj[cond] = t
            traj_n[cond] = d.groupby("n_tables")["schema"].nunique()

    big = sizes[-1]
    small = sizes[0]
    sent = []
    sent.append(
        f"At {small} tables Qwen2.5-3B averaged {comp.loc[small, 'Qwen2.5-3B round 0']} "
        f"layout problems per diagram (Graphviz neato: {comp.loc[small, 'Graphviz neato']}, "
        f"random placement: {comp.loc[small, 'Random placement']}). At {big} tables it averaged "
        f"{comp.loc[big, 'Qwen2.5-3B round 0']} (Graphviz neato: {comp.loc[big, 'Graphviz neato']}, "
        f"random placement: {comp.loc[big, 'Random placement']}).")
    v_all = int(r0["valid"].sum())
    sent.append(f"{v_all} of {n_schemas} first attempts were valid JSON with every table present. "
                "All averages above use valid layouts only.")

    def reg_row(cond, rnd):
        if reg.empty:
            return None
        m = reg[(reg.condition == cond) & (reg["round"] == rnd)]
        return None if m.empty else m.iloc[0]

    pr = reg_row("plain", f"0 to {rounds}")
    if pr is not None:
        sent.append(
            f"With the prompt \"Make sure the lines are not overlapping\", {pr['n']} schemas had a "
            f"valid layout both before and after {rounds} repair rounds. Compared with round 0, "
            f"{pr['worse_%']}% ended worse, {pr['same_%']}% unchanged and {pr['better_%']}% better "
            f"(mean change in problems: {pr['mean_change']}).")
        per_round = []
        for k in range(1, rounds + 1):
            r = reg_row("plain", str(k))
            if r is not None:
                per_round.append(f"round {k}: {r['worse_%']}% worse ({r['n']} schemas)")
        if per_round:
            sent.append("Share of single repair rounds that made the layout worse: "
                        + "; ".join(per_round) + ".")
    fr = reg_row("feedback", f"0 to {rounds}")
    if fr is not None:
        sent.append(
            f"With the computed feedback prompt, {fr['n']} schemas had a valid layout before and "
            f"after {rounds} rounds. {fr['worse_%']}% ended worse, {fr['same_%']}% unchanged and "
            f"{fr['better_%']}% better (mean change: {fr['mean_change']}).")
        if pr is not None:
            a, b = float(fr["mean_change"]), float(pr["mean_change"])
            word = "lower than" if a < b else ("higher than" if a > b else "the same as")
            sent.append(f"The mean change with computed feedback was {word} the change with the "
                        f"vague prompt ({a} versus {b}). The two groups can contain different "
                        "schemas, so compare the full tables below before drawing conclusions.")

    out = []
    out.append("# Can a small model draw an ERD without lines hitting tables?\n")
    out.append(f"Model tested: [{cfg.get('model_id', MODEL_ID)}]"
               f"(https://huggingface.co/{cfg.get('model_id', MODEL_ID)}), greedy decoding. "
               f"{n_schemas} synthetic schemas, canvas {cfg.get('canvas_w')} x {cfg.get('canvas_h')}.\n")
    out.append("## 1. The blind spot\n\n" + ans["Q1"] + "\n")
    if ans.get("OBSERVATIONS") and PLACEHOLDER not in ans["OBSERVATIONS"]:
        out.append("### What I saw when I looked at the outputs\n\n" + ans["OBSERVATIONS"] + "\n")

    out.append("## 2. How I tested it\n")
    out.append(
        "**Model.** Qwen2.5-3B-Instruct has 3B parameters, inside the 0.6 to 6B range, has open "
        "weights, and fits in fp16 on a free Colab T4 GPU. It is a small model, not a frontier "
        "model. I did not test larger models, so these results show the gap at this scale and "
        "I cannot say how much of it carries over to frontier models.\n")
    out.append(
        f"**Data.** {n_schemas} random connected schemas with "
        f"{', '.join(str(s) for s in sizes)} tables (same number of each size, seed "
        f"{cfg.get('seed', SEED)}). Each schema has the foreign keys of a tree plus extra ones "
        "equal to about 40 percent of the number of tables, so the graphs contain cycles. Table width is fixed at 200 and height depends "
        "on the number of columns. The model is told these sizes and must choose only the "
        "top left (x, y) of every table. The relationships are given, so the model cannot drop or "
        "invent a line. Every failure measured is a placement failure.\n")
    out.append(
        "**Scoring.** Each relationship is drawn as a straight line between table centers. A "
        "layout's problem count is the number of overlapping table pairs, plus pairs of crossing "
        "lines that share no table, plus (line, table) pairs where a line passes through a "
        "table that is not one of its two ends. Tables outside the canvas are counted separately.\n")
    out.append(
        "**References.** Graphviz neato on the same sizes (a layout engine, so it shows what is "
        "achievable; it is not always zero because dense graphs force some crossings), and random "
        f"placement ({RANDOM_REPS} random layouts per schema).\n")
    out.append(
        f"**Repair test.** After round 0, the model was told \"Make sure the lines are not "
        f"overlapping. Return the full JSON.\" for {rounds} rounds, with the whole conversation "
        "kept in context. **Control.** The same rounds, but the prompt listed the exact problems "
        "found by the scoring code (for example which line crosses which line), up to "
        f"{MAX_ISSUES_IN_FEEDBACK} per round.\n")

    out.append("## Results\n")
    out.append("\n\n".join(sent) + "\n")
    out.append("### Average problems per layout (lower is better)\n\n" + md_table(comp) + "\n")
    out.append("### Problems per foreign key\n\n" + md_table(comp_pe) + "\n")
    out.append("### Valid JSON layouts on the first attempt\n\n"
               + md_table(validity[["valid layouts", "schemas", "share valid"]]) + "\n")
    out.append("### What kind of problems the model's first attempts had\n\n"
               + md_table(breakdown) + "\n")
    def traj_note(cond):
        counts = ", ".join(f"{n} tables: {c}" for n, c in traj_n[cond].items())
        return ("Only schemas with a valid layout in every round are averaged, so the rounds "
                f"are comparable. Schemas per size: {counts}.\n\n")

    if "plain" in traj:
        out.append("### Average problems by repair round, prompt: \"make sure the lines are not "
                   "overlapping\"\n\n" + traj_note("plain") + md_table(traj["plain"]) + "\n")
    if "feedback" in traj:
        out.append("### Average problems by repair round, prompt: computed feedback (control)\n\n"
                   + traj_note("feedback") + md_table(traj["feedback"]) + "\n")
    if not reg.empty:
        out.append("### Did a repair round make the layout worse?\n\n"
                   + md_table(reg, index=False) + "\n")

    out.append(
        "### Limits of this study\n\n"
        f"- One model, one prompt wording, greedy decoding, {n_schemas} schemas. Differences "
        "between small groups can be noise.\n"
        "- Lines are straight center to center segments. Real ERD tools route lines "
        "differently, so absolute counts are specific to this metric.\n"
        "- Averages use valid layouts only. Invalid outputs are reported separately.\n"
        "- The Graphviz reference is a good layout engine, not a proof of the minimum number of "
        "crossings.\n")

    out.append("## 3. Path forward\n\n" + ans["Q3"] + "\n")

    out.append(
        "## Files in this bucket\n\n"
        "- `README.md` this file\n"
        "- `erd_eval.py` the full code: dataset generation, scoring, model runs, analysis\n"
        "- `schemas.json` the 40 evaluation schemas with table sizes\n"
        "- `round0_raw.json`, `repair_raw.json`, `feedback_raw.json` raw model outputs\n"
        "- `model_scores.csv`, `baseline_scores.csv`, `regression_rates.csv`, "
        "`results_summary.md` scores and tables\n"
        "- `figures/` plots and before and after layout images\n"
        "- `config.json` canvas size, seed and model id\n"
        "- `model/` copy of the model weights, if the copy step succeeded\n\n"
        "To reproduce: run `python erd_eval.py --workdir out` on a GPU machine with "
        "transformers, accelerate, shapely, networkx, pandas, matplotlib and Graphviz installed.\n")

    with open(path_in(workdir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"[readme] wrote {path_in(workdir, 'README.md')}")


def stage_publish(workdir, bucket_name, copy_model, dry_run):
    readme_path = path_in(workdir, "README.md")
    if not os.path.exists(readme_path):
        sys.exit("README.md not found. Run the README step first.")
    text = open(readme_path, encoding="utf-8").read()
    if PLACEHOLDER in text:
        sys.exit("README.md still contains the answer placeholder. Fill in your answers "
                 "and rebuild the README.")
    problems = answer_problems(read_answers(workdir))
    if problems:
        sys.exit("Fix your answers first:\n  - " + "\n  - ".join(problems))

    script_dst = path_in(workdir, "erd_eval.py")
    if os.path.abspath(__file__) != os.path.abspath(script_dst):
        import shutil
        shutil.copyfile(os.path.abspath(__file__), script_dst)

    skip = {".ipynb_checkpoints", "__pycache__"}
    files = []
    for root, dirs, names in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in skip]
        for n in names:
            if not n.endswith(".tmp"):
                files.append(os.path.relpath(os.path.join(root, n), workdir))
    print(f"[publish] {len(files)} files to upload:")
    for f in sorted(files):
        print("  ", f)
    if dry_run:
        print("[publish] dry run, nothing uploaded")
        return

    try:
        from huggingface_hub import (HfApi, bucket_info, create_bucket,
                                     list_bucket_tree, sync_bucket,
                                     update_bucket_settings)
    except ImportError:
        sys.exit("Your huggingface_hub is too old for Buckets. Run: "
                 "pip install -U huggingface_hub  and then run this step again.")

    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception as e:
        sys.exit(f"Not logged in to Hugging Face ({e}). Run the login cell first with a "
                 "token that has write access.")

    url = create_bucket(bucket_name, private=False, exist_ok=True)
    bucket_id = url.bucket_id
    print(f"[publish] bucket: {bucket_id}")

    sync_bucket(workdir, f"hf://buckets/{bucket_id}", exclude=["*.tmp"])
    print("[publish] files uploaded")

    if copy_model:
        try:
            api.copy_files(f"hf://{MODEL_ID}/", f"hf://buckets/{bucket_id}/model/")
            print("[publish] model weights copied into the bucket")
        except Exception as e:
            print(f"[publish] could not copy the model into the bucket ({e}). "
                  f"This is optional: the README links to {MODEL_ID}.")

    if bucket_info(bucket_id).private:
        update_bucket_settings(bucket_id, private=False)
    info = bucket_info(bucket_id)
    top = [item.path for item in list_bucket_tree(bucket_id, recursive=False)]
    print(f"[publish] public: {not info.private}, files: {info.total_files}")
    print("[publish] top level:", ", ".join(sorted(top)))
    if "README.md" not in top:
        print("WARNING: README.md was not found at the bucket root.")
    print("\nSUBMIT THIS LINK:\n  https://huggingface.co/buckets/" + bucket_id + "\n")


def main():
    global MODEL_ID
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="./erd_eval")
    ap.add_argument("--model", default=MODEL_ID)
    ap.add_argument("--stages", default="schemas,round0,repair,feedback,analyse")
    ap.add_argument("--limit-per-size", type=int, default=0,
                    help="use only the first N schemas of each size (quick test)")
    ap.add_argument("--rounds", type=int, default=REPAIR_ROUNDS)
    ap.add_argument("--mock", action="store_true",
                    help="use random fake model output to test the pipeline")
    ap.add_argument("--bucket-name", default="erd-layout-blindspot")
    ap.add_argument("--no-copy-model", action="store_true",
                    help="publish stage: do not copy the model weights into the bucket")
    ap.add_argument("--dry-run", action="store_true",
                    help="publish stage: list files but upload nothing")
    args = ap.parse_args()

    MODEL_ID = args.model
    os.makedirs(args.workdir, exist_ok=True)
    stages = [x.strip() for x in args.stages.split(",")]

    schemas = subset(stage_schemas(args.workdir), args.limit_per_size)
    gen = None
    if any(x in stages for x in ["round0", "repair", "feedback"]):
        gen = lazy_generator(args.mock)

    round0 = load_json(path_in(args.workdir, "round0_raw.json"), {})
    if "round0" in stages:
        round0 = stage_round0(args.workdir, schemas, gen)
    if "repair" in stages:
        stage_followups(args.workdir, schemas, gen, round0, "repair_raw.json", "r",
                        lambda prev, s: REPAIR_MSG, "repair", args.rounds)
    if "feedback" in stages:
        stage_followups(args.workdir, schemas, gen, round0, "feedback_raw.json", "fb",
                        feedback_message, "feedback", args.rounds)
    if "analyse" in stages:
        repair = load_json(path_in(args.workdir, "repair_raw.json"), {})
        feedback = load_json(path_in(args.workdir, "feedback_raw.json"), {})
        stage_analyse(args.workdir, schemas, round0, repair, feedback, args.rounds)
    if "readme" in stages:
        stage_readme(args.workdir)
    if "publish" in stages:
        stage_publish(args.workdir, args.bucket_name, not args.no_copy_model, args.dry_run)


if __name__ == "__main__":
    main()

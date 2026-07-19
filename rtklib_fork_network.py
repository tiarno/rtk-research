"""
RTKLIB fork/supply-chain network analysis
==========================================

Pulls the GitHub fork tree for tomojitakasu/RTKLIB and computes centrality
metrics to find high-leverage disclosure/patch chokepoints — i.e. which
forks, if they never pull an upstream security fix, leave the largest
share of the downstream ecosystem exposed.

Same pipeline shape as the sanctions-evasion / ALPR network analyses:
    extraction (GitHub API) -> cleaning -> graph construction (networkx)
    -> centrality analysis (betweenness / degree)

Requires:
    pip install requests networkx --break-system-packages

Set a GITHUB_TOKEN env var to raise the API rate limit from 60/hr
(unauthenticated) to 5000/hr — with ~1.8k forks plus their sub-forks,
you will hit the unauthenticated limit almost immediately.

Usage:
    export GITHUB_TOKEN=ghp_xxxxxxxx
    python rtklib_fork_network.py
"""
import argparse
import csv
import json
import os
import time
import requests
import networkx as nx

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

ROOT_OWNER, ROOT_REPO = "tomojitakasu", "RTKLIB"
CACHE_PATH = "rtklib_fork_cache.json"
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_NODES = 2000
SEED_NODES_PATH = "rtklib_seed_nodes.csv"
CACHE = {}


def load_cache():
    global CACHE
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            CACHE = json.load(fh)
    else:
        CACHE = {}


load_cache()


def save_cache():
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(CACHE, fh, indent=2)


def gh_get(url, params=None):
    """GET with basic rate-limit backoff."""
    while True:
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 5)
            print(f"  rate limited, sleeping {wait:.0f}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r


def sanitize_attrs(attrs):
    """Convert None values to graph-safe defaults for GraphML output."""
    cleaned = {}
    for key, value in attrs.items():
        if value is None:
            cleaned[key] = "" if not isinstance(key, str) else ""
        elif isinstance(value, (int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def load_seed_nodes(path=SEED_NODES_PATH):
    """Load the curated seed-node list from the supplied CSV file."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


def build_seed_graph(path=SEED_NODES_PATH):
    """Create a base supply-chain graph from the manually curated seed list."""
    G = nx.DiGraph()
    root_id = f"{ROOT_OWNER}/{ROOT_REPO}"
    G.add_node(
        root_id,
        stars=0,
        depth=0,
        description="upstream (official)",
        type="repo",
        category="official upstream",
        confidence="verified",
    )
    for row in load_seed_nodes(path):
        node_id = row["node"]
        attrs = {
            "type": row.get("type", "unknown"),
            "category": row.get("category", "unknown"),
            "region": row.get("region", ""),
            "confidence": row.get("confidence", ""),
            "notes": row.get("notes", ""),
            "source": row.get("source", ""),
        }
        G.add_node(node_id, **sanitize_attrs(attrs))
        G.add_edge(root_id, node_id, relation="seed")
    return G


def get_forks(owner, repo, per_page=100):
    """Yield all DIRECT forks of owner/repo, using a JSON cache when available."""
    repo_id = f"{owner}/{repo}"
    if repo_id in CACHE:
        print(f"using cached forks for {repo_id}")
        yield from CACHE[repo_id]
        return

    if not TOKEN:
        print(f"no GITHUB_TOKEN and no cache for {repo_id}; returning empty list")
        return

    page = 1
    while True:
        r = gh_get(
            f"{API}/repos/{owner}/{repo}/forks",
            params={"per_page": per_page, "page": page, "sort": "oldest"},
        )
        batch = r.json()
        if not batch:
            return
        CACHE[repo_id] = batch
        save_cache()
        yield from batch
        page += 1


def build_fork_graph(owner, repo, max_depth=3, max_nodes=40):
    """
    BFS through the fork tree.

    The script is intentionally capped to keep a partial but useful graph
    under GitHub's rate limits. When the cache is present, it can run fully
    offline and still produce a graph for analysis.
    """
    G = nx.DiGraph()
    root_id = f"{owner}/{repo}"
    G.add_node(root_id, stars=0, depth=0, description="upstream (official)")

    frontier = [(owner, repo, 0)]
    seen = {root_id}

    while frontier:
        o, r, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        if G.number_of_nodes() >= max_nodes:
            print(f"reached max_nodes={max_nodes}; stopping early")
            break

        node_id = f"{o}/{r}"
        print(f"expanding {node_id} (depth {depth})...")
        for fork in get_forks(o, r):
            if G.number_of_nodes() >= max_nodes:
                break
            fid = fork["full_name"]
            if fid in seen:
                continue
            seen.add(fid)
            G.add_node(
                fid,
                stars=fork.get("stargazers_count", 0),
                pushed_at=fork.get("pushed_at"),
                description=(fork.get("description") or "")[:120],
                depth=depth + 1,
            )
            G.add_edge(node_id, fid, relation="fork_of")
            if fork.get("forks_count", 0) > 0:
                frontier.append((fork["owner"]["login"], fork["name"], depth + 1))

    return G


def analyze(G, top_n=20):
    """Rank nodes by branching / chokepoint metrics."""
    betweenness = nx.betweenness_centrality(G.to_undirected())
    out_degree = dict(G.out_degree())
    in_degree = dict(G.in_degree())

    ranked = sorted(
        G.nodes,
        key=lambda n: (out_degree.get(n, 0), in_degree.get(n, 0), betweenness[n]),
        reverse=True,
    )

    print(f"\nTop {top_n} nodes by branching and chokepoint value:")
    print(f"{'repo':45s} {'out_degree':>10s} {'in_degree':>10s} {'betweenness':>12s} {'stars':>6s}")
    for n in ranked[:top_n]:
        stars = G.nodes[n].get("stars", "?")
        print(
            f"{n:45s} {out_degree.get(n, 0):10d} {in_degree.get(n, 0):10d} "
            f"{betweenness[n]:12.4f} {str(stars):>6s}"
        )

    return betweenness, out_degree, in_degree


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a partial RTKLIB fork graph")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    args = parser.parse_args()

    print(
        f"Building fork graph for {ROOT_OWNER}/{ROOT_REPO} "
        f"(using the supplied seed nodes as a local fallback; full GitHub crawling requires a token)\n"
    )
    G = build_seed_graph()
    print(f"Seed graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    if TOKEN:
        fork_graph = build_fork_graph(
            ROOT_OWNER,
            ROOT_REPO,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
        )
        for node, attrs in fork_graph.nodes(data=True):
            if node not in G:
                G.add_node(node, **sanitize_attrs(attrs))
        for src, dst, attrs in fork_graph.edges(data=True):
            if not G.has_edge(src, dst):
                G.add_edge(src, dst, **sanitize_attrs(attrs))
        print(f"Merged fork graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    else:
        print("No GITHUB_TOKEN detected; using the seed-node graph only.")

    print(f"\nGraph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    out_path = "rtklib_fork_graph.graphml"
    nx.write_graphml(G, out_path)
    print(f"Saved {out_path} — open in Gephi for visual exploration/layout")

    if G.number_of_nodes() < 10:
        print("Warning: this graph is a partial snapshot because the API was rate-limited or cached data was used.")

    analyze(G)

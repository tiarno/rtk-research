# Handoff Notes

## Overview

This document captures the current state of the RTKLIB research workspace, including outstanding tasks and suggested next actions.

## Current Focus

- Review and refine the fork graph analysis.
- Document the key RTKLIB relationships and findings.
- Keep the repository organized and easy to navigate.

## Network Interpretation — RETRACTED

An earlier version of this document claimed that `rtklibexplorer/RTKLIB` is the
dominant hub of the fork network, with upstream "clearly secondary." **That
conclusion is withdrawn — it was an artifact of an incomplete crawl, not a
property of the ecosystem.**

Two defects produced it:

1. **Truncated crawl.** `get_forks()` in `rtklib_fork_network.py` assigns
   `CACHE[repo_id] = batch` inside the pagination loop, so each page overwrites
   the previous one, and a cache *hit* short-circuits the crawl entirely. The
   resulting graph covers ~6% of upstream's ~1,800 forks (and the oldest ones,
   since the API call sorts by `oldest`) against ~100% of rtklibexplorer's 367.
   The hub was manufactured by the sampling.
2. **Centrality is meaningless on this graph.** GitHub fork graphs are trees —
   every fork has exactly one parent. Betweenness centrality on a tree is a
   monotone function of subtree size, so it cannot surface a chokepoint that
   simple descendant-counting would miss. The extraction → graph → centrality
   pipeline borrowed from the ALPR/sanctions work does not transfer here.

Separately, fork count measures curiosity, not deployment: a fork is one click,
and most are never touched again.

The fork-mapping line of work has been **dropped**. `rtklib_fork_network.py`,
`rtklib_fork_cache.json`, `rtklib_fork_graph.graphml`, and
`rtklib_seed_nodes.csv` are retained only as a record of the attempt. Do not
cite any figure from them.

## Suggested Next Steps

See [research/README.md](../research/README.md) — the project has moved to
direct analysis of the RTKLIB RTCM3 decoder.

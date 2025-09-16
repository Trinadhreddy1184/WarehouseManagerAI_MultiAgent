# Troubleshooting

## Diagnosing high memory usage on small instances

Running the full stack on a `t3.small` (2 GiB RAM) leaves little headroom once
Docker, PostgreSQL and the Python application are all running. The commands
below help pinpoint which component is consuming memory:

```sh
# Check overall system memory
free -h

# Inspect container usage (PostgreSQL is usually the heaviest)
docker stats warehousemanagerai_db

# Inspect Python processes (Streamlit UI, agents, background tasks)
ps -o pid,ppid,comm,rss,args -C python3 | sort -k4 -n
```

If Docker is disabled and you are running PostgreSQL locally, substitute
`docker stats` with `psql`/`pg_ctl` process listings.

## Strategies to reduce memory pressure

- **Reuse the provisioned PostgreSQL instance.** The application now streams the
  S3 SQL dump into temporary files when building the DuckDB mirror, avoiding the
  gigabyte‑scale in‑memory buffers that previously caused spikes during setup.
- **Disable the DuckDB fallback** when memory is tight by setting
  `ENABLE_DUCKDB_FALLBACK=false` in `.env`. The primary PostgreSQL database will
  continue to handle all queries, and you can re‑enable the fallback once more
  resources are available.
- **Reduce background syncing cost.** If you need the fallback but want to limit
  its refresh frequency, set `DUCKDB_AUTO_SYNC=false` or increase
  `DUCKDB_SYNC_INTERVAL` to a larger value (in seconds) so the mirror only
  rebuilds occasionally.
- **Keep pip lean.** `run_all.sh` installs dependencies with
  `pip install --no-cache-dir` to avoid caching wheels inside the instance. When
  updating dependencies manually, use the same flag and clear out `~/.cache/pip`
  if space is low.
- **Audit artifact sizes.** The downloaded SQL dump and DuckDB mirror both live
  under `data/`. Check their footprints with `du -h data` and prune old dumps if
  you generate them manually.

These adjustments keep the memory footprint within the limits of a `t3.small`
while preserving the ability to fall back to DuckDB when PostgreSQL is
unreachable.

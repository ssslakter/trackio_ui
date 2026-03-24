from typing import Optional, Union, NamedTuple
import orjson, polars as pl
import pandas as pd, numpy as np
from pathlib import Path
from datetime import datetime
from fastlite import *


class MetricsResult(NamedTuple):
    """Container for both step-indexed and timestamp-indexed metrics."""

    step_metrics: dict[str, pd.DataFrame]
    system_metrics: dict[str, pd.DataFrame]


class TrackioDatabase:
    def __init__(self, project_name: str, trackio_root: Optional[str] = None):
        self.project_name = project_name
        root = Path(trackio_root or "~/.cache/huggingface/trackio")
        self.db_path = Path(root / f"{project_name}.db").expanduser()
        self.db = database(self.db_path)
        self._cache: dict[str, pd.DataFrame] = {}
        self._system_cache: dict[str, pd.DataFrame] = {}

    def clear_cache(self):
        """Clears the in-memory cache."""
        self._cache.clear()
        self._system_cache.clear()

    def get_runs(self, names_only: bool = True) -> Union[list[dict], list[str]]:
        """Returns a list of all runs in the project. Each run contains keys ['id', 'run_name', 'config', 'created_at']."""
        runs: list[dict] = self.db.t.configs()
        runs = sorted(runs, key=lambda x: x["created_at"], reverse=True)
        if names_only:
            return [r["run_name"] for r in runs]
        for r in runs:
            r.update(orjson.loads(r.pop("config")))
        return runs

    def get_run_starts(self, run_names: list[str]) -> dict[str, float]:
        """Returns the start timestamp (in unix seconds) for the given runs based on their created_at."""
        if not run_names:
            return {}
        placeholders = ",".join(["?"] * len(run_names))
        res = self.db.q(
            f"SELECT run_name, config FROM configs WHERE run_name IN ({placeholders})",
            run_names,
        )
        return {r["run_name"]: datetime.fromisoformat(orjson.loads(r["config"])["_Created"]).timestamp() for r in res}

    def delete_runs(self, run_names: list[str]):
        """Deletes runs and their associated metrics."""
        if not run_names:
            return
        qry = f"run_name in ({','.join(['?'] * len(run_names))})"
        for t in ["configs", "metrics"]:
            getattr(self.db.t, t).delete_where(qry, run_names)
        if "system_metrics" in self.db.t:
            self.db.t.system_metrics.delete_where(qry, run_names)
        self.clear_cache()

    def get_metrics_raw(self, run_names: list[str]) -> list[dict]:
        """Returns metrics for the specified run names."""
        if not run_names:
            return []
        placeholders = ",".join(["?"] * len(run_names))
        m = self.db.t.metrics(f"run_name in ({placeholders})", run_names)
        s = []
        if "system_metrics" in self.db.t:
            s = self.db.t.system_metrics(f"run_name in ({placeholders})", run_names)
        return m + s

    def get_metrics(self, run_names: list[str], refresh: bool = True) -> MetricsResult:
        if isinstance(run_names, str):
            run_names = [run_names]
        missing_runs = run_names if refresh else [r for r in run_names if r not in self._cache and r not in self._system_cache]
        if missing_runs:
            raw_metrics = self.get_metrics_raw(missing_runs)
            if raw_metrics:
                result = process_metrics_to_dict(raw_metrics)
                self._cache.update(result.step_metrics)
                self._system_cache.update(result.system_metrics)

        step = {k: self._cache[k] for k in run_names if k in self._cache}
        system = {k: self._system_cache[k] for k in run_names if k in self._system_cache}
        return MetricsResult(step_metrics=step, system_metrics=system)

    def get_metrics_and_schema(self, run_names: list[str], refresh: bool = True) -> tuple[MetricsResult, list[str]]:
        """Fetches metrics and returns (MetricsResult, column_names) in one DB hit.

        Column names include both regular metric columns and system/* columns.
        """
        result = self.get_metrics(run_names, refresh=refresh)
        schema: list[str] = []

        if result.step_metrics:
            first_df = next(iter(result.step_metrics.values()))
            schema += [c for c in first_df.columns if c != "_timestamp"]

        if result.system_metrics:
            first_sys = next(iter(result.system_metrics.values()))
            schema += [f"system/{c}" for c in first_sys.columns]

        return result, schema

    def get_max_steps(self, run_names: list[str]) -> dict[str, int]:
        """Returns the maximum step currently in the database for the given runs."""
        if not run_names:
            return {}
        placeholders = ",".join(["?"] * len(run_names))
        res = self.db.q(
            f"SELECT run_name, MAX(step) as max_step FROM metrics WHERE run_name IN ({placeholders}) GROUP BY run_name",
            run_names,
        )
        return {r["run_name"]: r["max_step"] for r in res}

    def get_max_system_timestamps(self, run_names: list[str]) -> dict[str, float]:
        """Returns the maximum timestamp in system_metrics for the given runs."""
        if not run_names or "system_metrics" not in self.db.t:
            return {}
        placeholders = ",".join(["?"] * len(run_names))
        res = self.db.q(
            f"SELECT run_name, MAX(timestamp) as max_ts FROM system_metrics WHERE run_name IN ({placeholders}) GROUP BY run_name",
            run_names,
        )
        return {r["run_name"]: datetime.fromisoformat(r["max_ts"]).timestamp() for r in res}

    def fetch_new_metrics(self, run_states: dict[str, int]) -> dict[str, pd.DataFrame]:
        """Fetches newly inserted step-metrics strictly after the known step, merges into cache."""
        if not run_states:
            return {}

        conds = " OR ".join(["(run_name = ? AND step > ?)"] * len(run_states))
        params = []
        for r, s in run_states.items():
            params.extend([r, s])

        raw = self.db.q(f"SELECT run_name, step, metrics FROM metrics WHERE {conds}", params)
        if not raw:
            return {}

        result = process_metrics_to_dict(raw)
        updated_runs = {}
        for run, new_df in result.step_metrics.items():
            if run in self._cache:
                combined = pd.concat([self._cache[run], new_df])
                self._cache[run] = combined[~combined.index.duplicated(keep="last")].sort_index()
            else:
                self._cache[run] = new_df
            updated_runs[run] = self._cache[run]

        return updated_runs

    def fetch_new_system_metrics(self, run_states: dict[str, float]) -> dict[str, pd.DataFrame]:
        """Fetches newly inserted system metrics strictly after the known timestamp, merges into cache."""
        if not run_states or "system_metrics" not in self.db.t:
            return {}

        conds = " OR ".join(["(run_name = ? AND timestamp > ?)"] * len(run_states))
        params = []
        for r, ts in run_states.items():
            params.extend([r, ts])

        raw = self.db.q(f"SELECT run_name, timestamp, metrics FROM system_metrics WHERE {conds}", params)
        if not raw:
            return {}

        result = process_metrics_to_dict(raw)
        updated_runs = {}
        for run, new_df in result.system_metrics.items():
            if run in self._system_cache:
                combined = pd.concat([self._system_cache[run], new_df])
                self._system_cache[run] = combined[~combined.index.duplicated(keep="last")].sort_index()
            else:
                self._system_cache[run] = new_df
            updated_runs[run] = self._system_cache[run]

        return updated_runs


def process_metrics_to_dict(raw_metrics) -> MetricsResult:
    """
    Converts raw metrics into a MetricsResult with two separate dicts:
    - step_metrics: dict[run_name, DataFrame] indexed by integer step.
    - system_metrics: dict[run_name, DataFrame] indexed by float unix-second
      timestamp.
    """
    step_data: dict[tuple, dict] = {}
    system_data: dict[tuple, dict] = {}

    step_schema: dict[str, pl.DataType] = {"run_name": pl.Utf8, "step": pl.Int64}
    system_schema: dict[str, pl.DataType] = {"run_name": pl.Utf8, "timestamp": pl.Float64}

    for row in raw_metrics:
        run = row["run_name"]
        is_system = "timestamp" in row and "step" not in row

        raw_bytes = row["metrics"]
        if b"NaN" in raw_bytes:
            raw_bytes = raw_bytes.replace(b'"NaN"', b"null")
        new_metrics: dict = orjson.loads(raw_bytes)

        if is_system:
            ts = datetime.fromisoformat(row["timestamp"]).timestamp()
            key = (run, ts)
            system_schema.update({k: pl.Float64 for k in new_metrics.keys()})
            if key in system_data:
                system_data[key].update(new_metrics)
            else:
                new_metrics["run_name"] = run
                new_metrics["timestamp"] = ts
                system_data[key] = new_metrics
        else:
            step = row["step"]
            key = (run, step)
            step_schema.update({k: pl.Float64 for k in new_metrics.keys()})
            if key in step_data:
                step_data[key].update(new_metrics)
            else:
                new_metrics["run_name"] = run
                new_metrics["step"] = step
                step_data[key] = new_metrics

    step_results: dict[str, pd.DataFrame] = {}
    if step_data:
        df = pl.from_dicts(list(step_data.values()), schema=step_schema)
        for keys, sub_df in df.partition_by("run_name", as_dict=True).items():
            r_name = keys[0] if isinstance(keys, tuple) else keys
            step_results[r_name] = sub_df.drop("run_name").to_pandas().set_index("step").sort_index()

    system_results: dict[str, pd.DataFrame] = {}
    if system_data:
        df = pl.from_dicts(list(system_data.values()), schema=system_schema)
        for keys, sub_df in df.partition_by("run_name", as_dict=True).items():
            r_name = keys[0] if isinstance(keys, tuple) else keys
            system_results[r_name] = sub_df.drop("run_name").to_pandas().set_index("timestamp").sort_index()

    return MetricsResult(step_metrics=step_results, system_metrics=system_results)


def prepare_step_metrics(
    metrics: dict[str, pd.DataFrame],
    run_starts: dict[str, float],
    smoothing: float = 0,
    max_points: int = 0,
) -> dict:
    """
    Converts step-indexed DataFrames into the {run: {path: {x, y, ts?}}} payload
    consumed by the frontend.
    """
    processed_data = {}
    for run_name, df in metrics.items():
        if df.empty:
            continue

        run_start = run_starts.get(run_name, 0.0)
        has_ts = "_timestamp" in df.columns
        ts_col: Optional[np.ndarray] = df["_timestamp"].to_numpy() if has_ts else None
        value_df = df.drop(columns=["_timestamp"]) if has_ts else df

        if 0 < smoothing < 1.0:
            na_mask = value_df.isna()
            value_df = value_df.ewm(alpha=1 - smoothing).mean()
            value_df[na_mask] = np.nan

        idx_np = value_df.index.to_numpy()
        run_entry = {}

        for col in value_df.columns:
            vals = value_df[col].to_numpy()
            mask = ~np.isnan(vals)
            x = idx_np[mask]
            y = vals[mask]
            ts_series = ts_col[mask] if has_ts else None

            if len(x) == 0:
                continue

            if max_points != 0 and len(x) > max_points:
                if has_ts:
                    x, y, ts_series = min_max_downsample(x, y, int(max_points), aux=ts_series)
                else:
                    x, y = min_max_downsample(x, y, int(max_points))

            entry: dict = {"x": x, "y": np.round(y, 6)}
            if has_ts and ts_series is not None:
                entry["ts"] = np.round(ts_series - run_start, 2)
            run_entry[col] = entry

        if run_entry:
            processed_data[run_name] = run_entry

    return processed_data


def prepare_system_metrics(
    metrics: dict[str, pd.DataFrame],
    run_starts: dict[str, float],
    max_points: int = 0,
) -> dict:
    """
    Converts timestamp-indexed system metric DataFrames into the frontend payload.

    x values are relative run duration seconds. No smoothing is applied to system metrics.
    """
    processed_data = {}
    for run_name, df in metrics.items():
        if df.empty:
            continue

        ts_sec = df.index.to_numpy()
        run_start = run_starts.get(run_name, 0.0)
        run_entry = {}

        for col in df.columns:
            vals = df[col].to_numpy()
            mask = ~np.isnan(vals)
            x = ts_sec[mask]
            y = vals[mask]

            if len(x) == 0:
                continue

            if max_points != 0 and len(x) > max_points:
                x, y = min_max_downsample(x, y, int(max_points))

            run_entry[f"system/{col}"] = {"x": np.round(x - run_start, 2), "y": np.round(y, 6)}

        if run_entry:
            processed_data[run_name] = run_entry

    return processed_data


def min_max_downsample(x, y, target_points, aux: Optional[np.ndarray] = None):
    """LTTB-style min/max downsampler."""
    n = len(y)
    if n <= target_points:
        return (x, y, aux) if aux is not None else (x, y)

    target_chunks = max(1, int(target_points) // 2)
    chunk_size = max(1, n // target_chunks)
    num_chunks = n // chunk_size
    trunc_len = num_chunks * chunk_size

    y_trunc = y[:trunc_len].reshape(num_chunks, chunk_size)
    offsets = np.arange(num_chunks) * chunk_size
    min_idx = np.argmin(y_trunc, axis=1) + offsets
    max_idx = np.argmax(y_trunc, axis=1) + offsets

    arrays_to_concat = [min_idx, max_idx, [n - 1]]
    if trunc_len < n:
        rem_y = y[trunc_len:]
        arrays_to_concat.insert(
            2,
            [trunc_len + np.argmin(rem_y), trunc_len + np.argmax(rem_y)],
        )

    final_indices = np.unique(np.concatenate(arrays_to_concat)).astype(int)

    if aux is not None:
        return x[final_indices], y[final_indices], aux[final_indices]
    return x[final_indices], y[final_indices]

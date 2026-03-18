from typing import Optional, Union
import orjson, polars as pl
import pandas as pd, numpy as np
from pathlib import Path
from fastlite import *


class TrackioDatabase:
    def __init__(self, project_name: str, trackio_root: Optional[str] = None):
        self.project_name = project_name
        root = Path(trackio_root or "~/.cache/huggingface/trackio")
        self.db_path = Path(root / f"{project_name}.db").expanduser()
        self.db = database(self.db_path)
        self._cache = {}

    def clear_cache(self):
        """Clears the in-memory cache."""
        self._cache.clear()

    def get_runs(self, names_only: bool = True) -> Union[list[dict], list[str]]:
        """Returns a list of all runs in the project. Each run contains keys ['id', 'run_name', 'config', 'created_at']."""
        runs: list[dict] = self.db.t.configs()
        runs = sorted(runs, key=lambda x: x["created_at"], reverse=True)
        if names_only:
            return [r["run_name"] for r in runs]
        for r in runs:
            r.update(orjson.loads(r.pop("config")))
        return runs

    def delete_runs(self, run_names: list[str]):
        """Deletes runs and their associated metrics."""
        if not run_names:
            return
        qry = f"run_name in ({','.join(['?'] * len(run_names))})"
        for t in ["configs", "metrics"]:
            getattr(self.db.t, t).delete_where(qry, run_names)
        self.clear_cache()

    def get_metrics_raw(self, run_names: list[str]) -> list[dict]:
        """Returns metrics for the specified run names."""
        if not run_names:
            return []
        return self.db.t.metrics(f"run_name in ({','.join(['?'] * len(run_names))})", run_names)

    def get_metrics(self, run_names: list[str], refresh: bool = True) -> dict:
        if isinstance(run_names, str):
            run_names = [run_names]
        missing_runs = run_names if refresh else [r for r in run_names if r not in self._cache]
        if missing_runs:
            raw_metrics = self.get_metrics_raw(missing_runs)
            if raw_metrics:
                self._cache.update(process_metrics_to_dict(raw_metrics))
        return {k: self._cache[k] for k in run_names if k in self._cache}

    def get_metrics_and_schema(self, run_names: list[str], refresh: bool = True) -> tuple[dict, list[str]]:
        """Fetches metrics and returns (metrics_dict, column_names) in one DB hit."""
        metrics = self.get_metrics(run_names, refresh=refresh)
        if not metrics:
            return metrics, []
        schema = next(iter(metrics.values())).columns.tolist()
        return metrics, schema


def process_metrics_to_dict(raw_metrics) -> dict[str, pd.DataFrame]:
    """
    Converts raw metrics into a Dictionary of DataFrames keyed by run_name.
    """
    merged_data = {}
    schema = {"run_name": pl.Utf8, "step": pl.Int64}
    for row in raw_metrics:
        run, step = row["run_name"], row["step"]
        key = (run, step)
        raw_bytes = row["metrics"]
        if b"NaN" in raw_bytes:
            raw_bytes = raw_bytes.replace(b'"NaN"', b"null")
        new_metrics = orjson.loads(raw_bytes)
        schema.update({k: pl.Float64 for k in new_metrics.keys()})

        if key in merged_data:
            merged_data[key].update(new_metrics)
        else:
            new_metrics["run_name"] = run
            new_metrics["step"] = step
            merged_data[key] = new_metrics

    if not merged_data:
        return {}

    df = pl.from_dicts(list(merged_data.values()), schema=schema)
    partitions = df.partition_by("run_name", as_dict=True)
    results = {}
    for keys, sub_df in partitions.items():
        r_name = keys[0] if isinstance(keys, tuple) else keys
        results[r_name] = sub_df.drop("run_name").to_pandas().set_index("step").sort_index()

    return results


def apply_downsampling(df: pd.DataFrame, stride: int) -> pd.DataFrame:
    """
    Reduces rows by 'stride' while ensuring rows containing
    sparse metrics (mostly NaN columns) are preserved.
    """
    if stride <= 1:
        return df

    column_density = df.count() / len(df)
    sparse_cols = column_density[column_density < 0.9].index

    stride_mask = np.arange(len(df)) % stride == 0

    if not sparse_cols.empty:
        sparse_mask = df[sparse_cols].notna().any(axis=1)
        return df[stride_mask | sparse_mask]

    return df[stride_mask]


def prepare_metrics(metrics: dict[str, pd.DataFrame], smoothing: float = 0, max_points: int = 0):
    processed_data = {}
    for run_name, df in metrics.items():
        if df.empty:
            continue

        if 0 < smoothing < 1.0:
            na_mask = df.isna()
            df = df.ewm(alpha=1 - smoothing).mean()
            df[na_mask] = np.nan

        idx_np = df.index.to_numpy()
        run_entry = {}
        for col in df.columns:
            vals = df[col].to_numpy()

            mask = ~np.isnan(vals)
            x = idx_np[mask]
            y = vals[mask]
            if max_points != 0 and len(x) > max_points:
                x, y = min_max_downsample(x, y, int(max_points))

            y = np.round(y, 6)

            run_entry[col] = {"x": x, "y": y}

        processed_data[run_name] = run_entry

    return processed_data


def min_max_downsample(x, y, target_points):
    n = len(y)
    if n <= target_points:
        return x, y

    num_chunks = target_points // 2
    chunk_size = n // num_chunks
    limit = num_chunks * chunk_size

    y_reshaped = y[:limit].reshape(num_chunks, chunk_size)

    arg_mins = np.argmin(y_reshaped, axis=1)
    arg_maxs = np.argmax(y_reshaped, axis=1)

    chunk_offsets = np.arange(0, limit, chunk_size)
    idx_mins = arg_mins + chunk_offsets
    idx_maxs = arg_maxs + chunk_offsets

    final_indices = np.concatenate([idx_mins, idx_maxs, [n - 1]])

    final_indices.sort()

    return x[final_indices], y[final_indices]

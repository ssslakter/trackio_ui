from typing import Optional, Union
import orjson, polars as pl
import pandas as pd, numpy as np
from pathlib import Path
from fastlite import *


class TrackioDatabase:
    def __init__(self, project_name: str, trackio_root: Optional[str] = None):
        self.project_name = project_name
        trackio_root = trackio_root or Path("~/.cache/huggingface/trackio")
        self.db_path = Path(trackio_root / f"{project_name}.db").expanduser()
        self.db = database(self.db_path)
        self._cache = {}

    def clear_cache(self):
        """Clears the in-memory cache."""
        self._cache.clear()

    def get_runs(self, names_only: bool = True) -> Union[list[dict], list[str]]:
        """Returns a list of all runs in the project. Each run contains keys ['id', 'run_name', 'config', 'created_at']."""
        runs = self.db.t.configs()
        if names_only:
            return [r["run_name"] for r in sorted(runs, key=lambda x: x["created_at"])]
        return runs

    def get_metrics_raw(self, run_names: list[str]) -> list[dict]:
        """Returns metrics for the specified run names."""
        if not run_names:
            return []
        return self.db.t.metrics(f"run_name in ({','.join(['?']*len(run_names))})", run_names)

    def get_metrics(self, run_names: Union[list[str], str, None] = None, refresh: bool = False) -> pd.DataFrame:
        """
        Returns a DataFrame of metrics.
        Checks cache first, only fetches missing runs from DB.

        :param refresh: If True, ignores cache and re-fetches specified runs from DB.
        """
        if run_names is None:
            all_configs = self.get_runs()
            run_names = [c["run_name"] for c in all_configs]
        elif isinstance(run_names, str):
            run_names = [run_names]

        missing_runs = run_names if refresh else [r for r in run_names if r not in self._cache]

        if missing_runs:
            raw_metrics = self.get_metrics_raw(missing_runs)
            if raw_metrics:
                new_dfs = process_metrics_to_dict(raw_metrics)
                self._cache.update(new_dfs)

        return {k: self._cache[k] for k in run_names}


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


def prepare_metrics(metrics: dict[str, pd.DataFrame], smoothing: float = 0, downsample: int = 1):
    processed_data = {}
    for run_name, df in metrics.items():
        if df.empty:
            continue

        df = df.copy()
        na_mask = df.isna()
        if 0 < smoothing < 1.0:
            df = df.ewm(alpha=1 - smoothing).mean()
            df[na_mask] = np.nan
        df = apply_downsampling(df, downsample)
        df = df.reset_index().round(6)
        processed_data[run_name] = df.to_dict(orient="list")
    return processed_data

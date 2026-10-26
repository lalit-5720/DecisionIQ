import numpy as np


def evaluate(actual: np.ndarray, pred: np.ndarray) -> dict:
    """actual/pred: (series, days). MAPE ignores zero-demand days; `mape_agg` is on daily totals across series."""
    err = actual - pred
    nz = actual > 0
    ss_res, ss_tot = (err**2).sum(), ((actual - actual.mean()) ** 2).sum()
    tot_a, tot_p = actual.sum(axis=0), pred.sum(axis=0)
    return {
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "mape": float((np.abs(err[nz]) / actual[nz]).mean() * 100),
        "wape": float(np.abs(err).sum() / actual.sum() * 100),
        "mape_agg": float((np.abs(tot_a - tot_p) / np.maximum(tot_a, 1)).mean() * 100),
        "r2": float(1 - ss_res / ss_tot),
    }

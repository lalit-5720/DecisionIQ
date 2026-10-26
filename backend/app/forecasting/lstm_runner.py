"""Runs the LSTM in a subprocess (TensorFlow import-order issue) and returns forecast + training time."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_lstm(y, dates, t_end, horizon, quick=False, save_model=None):
    """Train on y[:, :t_end] and forecast `horizon` days after t_end. Returns (forecast [n, horizon], train_seconds)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        np.save(tmp / "y.npy", y)
        np.save(tmp / "dates.npy", dates.to_numpy().astype("datetime64[ns]"))
        out = tmp / "fc.npy"
        job = {
            "y": str(tmp / "y.npy"), "dates": str(tmp / "dates.npy"), "t_end": int(t_end), "horizon": int(horizon),
            "samples": 20_000 if quick else 150_000, "epochs": 2 if quick else 5, "out": str(out),
            "save_model": str(save_model) if save_model else None,
        }
        (tmp / "job.json").write_text(json.dumps(job))
        proc = subprocess.run(
            [sys.executable, "-m", "app.forecasting.lstm_worker", str(tmp / "job.json")],
            cwd=BACKEND_DIR, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"LSTM worker failed: {proc.stderr[-600:]}")
        return np.load(out), json.loads(Path(str(out) + ".json").read_text())["train_s"]

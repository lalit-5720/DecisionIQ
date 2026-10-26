"""Subprocess entry point: python -m app.forecasting.lstm_worker <job.json>

Imports TensorFlow first (see lstm_model) so it can coexist with the rest of the stack.
"""
import json
import sys
import time

from app.forecasting import lstm_model  # noqa: I001  must stay first: imports tensorflow before numpy/pandas

import numpy as np
import pandas as pd


def main(job_path: str) -> None:
    job = json.load(open(job_path))
    y = np.load(job["y"])
    dates = pd.DatetimeIndex(pd.to_datetime(np.load(job["dates"])))
    t0 = time.perf_counter()
    model, scale = lstm_model.train(y, dates, job["t_end"], samples=job["samples"], epochs=job["epochs"])
    secs = time.perf_counter() - t0
    fc = lstm_model.forecast(model, scale, y[:, : job["t_end"]], dates, job["horizon"])
    np.save(job["out"], fc)
    if job.get("save_model"):
        model.save(job["save_model"])
    json.dump({"train_s": round(secs, 1)}, open(job["out"] + ".json", "w"))


if __name__ == "__main__":
    main(sys.argv[1])

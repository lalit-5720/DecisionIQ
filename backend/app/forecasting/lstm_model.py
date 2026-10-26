"""Global LSTM (Keras): 28-day window of normalised sales + calendar -> next day, forecast recursively."""
import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

# TensorFlow must be imported before numpy/pandas on this Windows setup (DLL conflict otherwise),
# so this module only runs inside the lstm_worker subprocess (see lstm_runner.py).
import tensorflow as tf  # noqa: E402  isort:skip

import numpy as np  # noqa: E402

from app.forecasting.data import extend_dates  # noqa: E402

WINDOW = 28


def _cal(dates):
    dow, doy = dates.dayofweek.to_numpy(), dates.dayofyear.to_numpy()
    return np.column_stack(
        [np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7), np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)]
    )


def _windows(yn, cal, s, t):
    """Input step k = (value of day t-W+k, calendar of the *following* day) so the last step carries day t's calendar."""
    idx = t[:, None] + np.arange(-WINDOW, 0)
    return np.concatenate([yn[s[:, None], idx][..., None], cal[idx + 1]], axis=2).astype(np.float32)


def train(y, dates, t_end, samples=150_000, epochs=5, seed=42):
    tf.keras.utils.set_random_seed(seed)
    rng = np.random.default_rng(seed)
    scale = np.maximum(y[:, :t_end].mean(axis=1), 1.0)
    yn = y / scale[:, None]
    cal = _cal(dates)
    s = rng.integers(0, y.shape[0], samples)
    t = rng.integers(WINDOW, t_end, samples)
    X, target = _windows(yn, cal, s, t), yn[s, t].astype(np.float32)
    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input((WINDOW, 5)),
            tf.keras.layers.LSTM(64),
            tf.keras.layers.Dense(32, activation="relu"),
            tf.keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="mse")
    model.fit(X, target, epochs=epochs, batch_size=512, verbose=0)
    return model, scale


def forecast(model, scale, y_hist, dates, horizon):
    n, T = y_hist.shape
    all_dates = extend_dates(dates[:T], horizon)
    cal = _cal(all_dates)
    yn = np.concatenate([y_hist / scale[:, None], np.zeros((n, horizon))], axis=1)
    s = np.arange(n)
    for h in range(horizon):
        t = np.full(n, T + h)
        pred = model(_windows(yn, cal, s, t), training=False).numpy().ravel()
        yn[:, T + h] = np.clip(pred, 0, None)
    return yn[:, T:] * scale[:, None]

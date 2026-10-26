"""Per-series statistical models (Prophet, SARIMA). Too slow for every series, so used on the benchmark sample."""
import logging
import warnings

import numpy as np
import pandas as pd

logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")


def prophet_forecast(y_series: np.ndarray, dates: pd.DatetimeIndex, horizon: int) -> np.ndarray:
    from prophet import Prophet

    m = Prophet(weekly_seasonality=True, yearly_seasonality=True, daily_seasonality=False, interval_width=0.95)
    m.fit(pd.DataFrame({"ds": dates, "y": y_series}))
    fut = pd.DataFrame({"ds": pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=horizon)})
    return np.clip(m.predict(fut)["yhat"].to_numpy(), 0, None)


def sarima_forecast(y_series: np.ndarray, horizon: int, tail: int = 730) -> np.ndarray:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    fit = SARIMAX(
        y_series[-tail:], order=(1, 1, 1), seasonal_order=(1, 0, 1, 7),
        enforce_stationarity=False, enforce_invertibility=False,
    ).fit(disp=False, maxiter=50)
    return np.clip(fit.forecast(horizon), 0, None)

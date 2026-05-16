"""
LSTM directional signal (Phase 3 of the Roan framework).

Per Roan's article 2: a small LSTM trained on STATIONARY features (log
returns over multiple horizons, vol ratio, momentum normalised by vol,
volume z-score) predicts the probability of a positive next-period return.

The expected directional accuracy on D1 equity indices is 52-57% per the
article -- a small edge, but if applied consistently as a CONFIRMATION
gate (only allow MR long entry if LSTM also predicts positive direction),
it can shave the worst entries.

Design choices that avoid the standard LSTM-on-finance failure modes:

1. **Stationary features only.** Per Roan article part 2: raw prices are
   non-stationary; the model learns the wrong distribution. Inputs are log
   returns, vol ratios, normalised momentum -- all approximately stationary.

2. **Binary classification target.** Not "predict the price tomorrow" --
   that's a regression to a non-stationary value. Just "will next return
   be positive?" (BCE loss).

3. **Small model + early stopping.** 2-layer LSTM, hidden_size=32,
   dropout=0.2. Stop training when validation loss stops decreasing for
   `patience` epochs. The smaller the model, the harder to overfit ~3000
   bars of training data.

4. **Walk-forward training.** Each backtest window trains its OWN model
   on the window's IS portion; OOS predictions use the IS-only model.
   No future leakage by construction.

5. **Per-symbol models.** Different markets have different microstructure;
   one model per symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# Try to import torch. Module is importable without it; gate creation fails.
try:
    import torch
    import torch.nn as nn
    _HAVE_TORCH = True
except ImportError:
    _HAVE_TORCH = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LSTMConfig:
    """Hyperparameters for the directional LSTM."""

    # Architecture
    hidden_size: int = 32
    num_layers: int = 2
    dropout: float = 0.2

    # Sequence
    lookback: int = 20
    """Bars of history the LSTM sees at each prediction."""

    # Features
    return_horizons: tuple[int, ...] = (1, 5, 20)
    vol_short: int = 5
    vol_long: int = 20

    # Training
    batch_size: int = 64
    learning_rate: float = 1e-3
    max_epochs: int = 50
    patience: int = 5
    seed: int = 42
    train_frac: float = 0.8
    """Fraction of bars used for training; remainder for validation early
    stopping."""

    # Inference
    long_entry_threshold: float = 0.55
    """Allow MR long entry only if LSTM P(up) >= this threshold."""


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


def build_features(df: pd.DataFrame, config: LSTMConfig) -> pd.DataFrame:
    """Construct the per-bar feature panel.

    All features are stationary or near-stationary. Returns a DataFrame
    indexed like the input; warmup bars are NaN.
    """
    close = df["close"]
    returns = close.pct_change()

    feats = pd.DataFrame(index=df.index)
    for h in config.return_horizons:
        feats[f"ret_{h}d"] = close.pct_change(h)

    vol_s = returns.rolling(config.vol_short).std()
    vol_l = returns.rolling(config.vol_long).std()
    feats["vol_ratio"] = vol_s / vol_l
    feats["momentum_norm"] = returns / vol_l

    if "tick_volume" in df.columns:
        vol = df["tick_volume"]
        vol_mean = vol.rolling(config.vol_long).mean()
        vol_std = vol.rolling(config.vol_long).std()
        feats["volume_zscore"] = (vol - vol_mean) / vol_std

    high_low_range = (df["high"] - df["low"]) / close
    feats["range_norm"] = high_low_range / high_low_range.rolling(config.vol_long).mean()

    return feats


def build_target(df: pd.DataFrame) -> pd.Series:
    """Binary target: 1 if next bar's close > current close, else 0.

    NaN on the last bar (no next bar available).
    """
    next_return = df["close"].pct_change().shift(-1)
    return (next_return > 0).astype(int).where(next_return.notna(), other=np.nan)


# ---------------------------------------------------------------------------
# LSTM model
# ---------------------------------------------------------------------------


if _HAVE_TORCH:

    class TradingLSTM(nn.Module):
        """Small LSTM -> linear head -> sigmoid for binary directional prediction.

        Input shape:  (batch_size, lookback, n_features)
        Output shape: (batch_size,) -- P(next return positive)
        """

        def __init__(self, n_features: int, hidden_size: int = 32,
                      num_layers: int = 2, dropout: float = 0.2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden_size,
                num_layers=num_layers,
                dropout=dropout if num_layers > 1 else 0.0,
                batch_first=True,
            )
            self.dropout = nn.Dropout(dropout)
            self.fc = nn.Linear(hidden_size, 1)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            out, _ = self.lstm(x)
            last = out[:, -1, :]            # last timestep's hidden state
            return torch.sigmoid(self.fc(self.dropout(last))).squeeze(-1)


# ---------------------------------------------------------------------------
# Sequence preparation
# ---------------------------------------------------------------------------


def make_sequences(features: pd.DataFrame, target: pd.Series,
                    lookback: int) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Turn feature panel + target into (X, y, index) numpy arrays.

    X shape: (n_samples, lookback, n_features)
    y shape: (n_samples,)
    index:   the timestamp of the bar AT WHICH the prediction is made (i.e.
             the last bar in each sequence; target[t] = direction of t+1).
    """
    df = features.join(target.rename("__target__"), how="inner").dropna()
    n_features = features.shape[1]
    if len(df) <= lookback:
        return (np.empty((0, lookback, n_features)),
                np.empty(0),
                pd.DatetimeIndex([]))

    fvals = df[features.columns].to_numpy().astype(np.float32)
    yvals = df["__target__"].to_numpy().astype(np.float32)

    n_seq = len(df) - lookback + 1
    X = np.zeros((n_seq, lookback, n_features), dtype=np.float32)
    y = np.zeros(n_seq, dtype=np.float32)
    for i in range(n_seq):
        X[i] = fvals[i: i + lookback]
        y[i] = yvals[i + lookback - 1]
    idx = df.index[lookback - 1:]
    return X, y, idx


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


@dataclass
class TrainResult:
    model: "TradingLSTM"
    feature_mean: np.ndarray
    feature_std: np.ndarray
    n_train: int
    n_val: int
    best_val_loss: float
    best_val_acc: float
    epochs_run: int


def train_lstm_on_window(
    features: pd.DataFrame,
    target: pd.Series,
    config: LSTMConfig,
) -> Optional[TrainResult]:
    """Train an LSTM on the given IS feature/target slice.

    Sequential train/val split (NEVER randomised -- random splits leak
    future info via the autocorrelation in financial returns).

    Returns None if torch isn't installed or there isn't enough data.
    """
    if not _HAVE_TORCH:
        return None

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)

    X, y, _idx = make_sequences(features, target, config.lookback)
    if len(X) < 100:
        return None  # not enough data to train meaningfully

    split = int(len(X) * config.train_frac)
    X_tr, X_vl = X[:split], X[split:]
    y_tr, y_vl = y[:split], y[split:]

    # Fit normalisation on training portion only
    feat_mean = X_tr.reshape(-1, X_tr.shape[-1]).mean(axis=0)
    feat_std = X_tr.reshape(-1, X_tr.shape[-1]).std(axis=0) + 1e-8

    X_tr_n = (X_tr - feat_mean) / feat_std
    X_vl_n = (X_vl - feat_mean) / feat_std

    X_tr_t = torch.from_numpy(X_tr_n)
    y_tr_t = torch.from_numpy(y_tr)
    X_vl_t = torch.from_numpy(X_vl_n)
    y_vl_t = torch.from_numpy(y_vl)

    model = TradingLSTM(
        n_features=X.shape[-1],
        hidden_size=config.hidden_size,
        num_layers=config.num_layers,
        dropout=config.dropout,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    criterion = nn.BCELoss()

    best_val_loss = float("inf")
    best_val_acc = 0.5
    patience_counter = 0
    epochs_run = 0
    best_state = None

    n_batches = max(1, len(X_tr_t) // config.batch_size)
    for epoch in range(config.max_epochs):
        epochs_run = epoch + 1
        model.train()
        # Mini-batch SGD with shuffled indices (within the training portion)
        order = np.random.permutation(len(X_tr_t))
        for b in range(n_batches):
            sel = order[b * config.batch_size: (b + 1) * config.batch_size]
            if len(sel) == 0:
                continue
            preds = model(X_tr_t[sel])
            loss = criterion(preds, y_tr_t[sel])
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        # Validation
        model.eval()
        with torch.no_grad():
            val_preds = model(X_vl_t)
            val_loss = criterion(val_preds, y_vl_t).item()
            val_acc = float(((val_preds > 0.5).float() == y_vl_t).float().mean())

        if val_loss < best_val_loss - 1e-5:
            best_val_loss = val_loss
            best_val_acc = val_acc
            patience_counter = 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= config.patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    return TrainResult(
        model=model,
        feature_mean=feat_mean,
        feature_std=feat_std,
        n_train=len(X_tr),
        n_val=len(X_vl),
        best_val_loss=best_val_loss,
        best_val_acc=best_val_acc,
        epochs_run=epochs_run,
    )


# ---------------------------------------------------------------------------
# Inference gate
# ---------------------------------------------------------------------------


class LSTMDirectionalGate:
    """Walk-forward LSTM directional confirmation gate.

    Trains a model ONCE on `prices[:initial_train_bars]`, then re-trains
    every `refit_every` bars. At each query bar, predicts P(next bar up);
    `allow_entry` returns True only if P > long_entry_threshold.
    """

    def __init__(
        self,
        prices_df: pd.DataFrame,
        config: LSTMConfig,
        initial_train_bars: int = 504,
        refit_every: int = 252,
    ) -> None:
        if not _HAVE_TORCH:
            raise RuntimeError("torch not installed; uv add torch")
        self._df = prices_df
        self._config = config
        self._initial_train = initial_train_bars
        self._refit_every = refit_every

        # Precompute features and target once (each is a function only of
        # past+current prices; the gate's walk-forward correctness comes
        # from WHICH BARS we train on, not from when we compute features).
        self._features = build_features(prices_df, config)
        self._target = build_target(prices_df)

        # (fit_bar_index, TrainResult) cache.
        self._cache: dict[int, TrainResult] = {}

    def _fit_at(self, bar_i: int) -> Optional[TrainResult]:
        if bar_i < self._initial_train:
            return None
        step = self._refit_every
        first = self._initial_train
        n_refits = (bar_i - first) // step
        fit_bar = first + n_refits * step
        if fit_bar in self._cache:
            return self._cache[fit_bar]
        feats_window = self._features.iloc[: fit_bar + 1]
        tgt_window = self._target.iloc[: fit_bar + 1]
        result = train_lstm_on_window(feats_window, tgt_window, self._config)
        if result is not None:
            self._cache[fit_bar] = result
        return result

    def predict_up_probability(self, bar_i: int) -> Optional[float]:
        """P(next bar's close > current close) at bar_i. None if warmup."""
        if not _HAVE_TORCH:
            return None
        result = self._fit_at(bar_i)
        if result is None:
            return None

        # Build a single sequence ending at bar_i.
        feats = self._features.iloc[: bar_i + 1].dropna()
        if len(feats) < self._config.lookback:
            return None
        window = feats.iloc[-self._config.lookback:].to_numpy().astype(np.float32)
        normed = (window - result.feature_mean) / result.feature_std
        x = torch.from_numpy(normed).unsqueeze(0)  # (1, lookback, n_features)
        result.model.eval()
        with torch.no_grad():
            p = float(result.model(x).item())
        return p

    def allow_entry(self, bar_i: int) -> bool:
        """The gate decision: True iff LSTM predicts P(up) > threshold."""
        p = self.predict_up_probability(bar_i)
        if p is None:
            return False  # warmup -> deny conservatively
        return bool(p >= self._config.long_entry_threshold)

    def latest_training_metrics(self, bar_i: int) -> Optional[dict]:
        """Diagnostic: report the most recent fit's val accuracy."""
        result = self._fit_at(bar_i)
        if result is None:
            return None
        return {
            "n_train": result.n_train,
            "n_val": result.n_val,
            "best_val_loss": result.best_val_loss,
            "best_val_acc": result.best_val_acc,
            "epochs_run": result.epochs_run,
        }

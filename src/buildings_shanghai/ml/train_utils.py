"""Module B — B3 训练工具模块

包含:
  - SMOTE-inside-CV 评估流程
  - GroupKFold 空间分组
  - 评估指标计算 (accuracy / macro-F1 / log_loss / bootstrap CI)
  - 特征重要性提取
  - 混淆矩阵 + 对比图生成
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    confusion_matrix,
)
from sklearn.model_selection import GroupKFold


# --------------------------------------------------------------------------- #
# 空间分组                                                                      #
# --------------------------------------------------------------------------- #
def make_spatial_groups(lat: np.ndarray, lon: np.ndarray, grid_deg: float) -> np.ndarray:
    """0.01° 网格 cell 编码为 GroupKFold 组 ID（整数）。"""
    cell_lat = np.floor(lat / grid_deg).astype(int)
    cell_lon = np.floor(lon / grid_deg).astype(int)
    combined = cell_lat.astype(str) + "_" + cell_lon.astype(str)
    _, groups = np.unique(combined, return_inverse=True)
    return groups


# --------------------------------------------------------------------------- #
# SMOTE / 上采样（fold 内部）                                                   #
# --------------------------------------------------------------------------- #
def resample_training_fold(
    X_tr: np.ndarray, y_tr: np.ndarray,
    k_neighbors: int, fallback_min_samples: int, rng_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """SMOTE 在 fold 内部；若任何类样本不足则 fallback 到 RandomOverSampler。"""
    from imblearn.over_sampling import SMOTE, RandomOverSampler

    counts = pd.Series(y_tr).value_counts()
    min_count = int(counts.min())

    if min_count < 2:
        return RandomOverSampler(random_state=rng_seed).fit_resample(X_tr, y_tr)

    if min_count < fallback_min_samples:
        k = min_count - 1
    else:
        k = k_neighbors

    try:
        return SMOTE(k_neighbors=k, random_state=rng_seed).fit_resample(X_tr, y_tr)
    except Exception:
        return RandomOverSampler(random_state=rng_seed).fit_resample(X_tr, y_tr)


# --------------------------------------------------------------------------- #
# Bootstrap CI                                                                  #
# --------------------------------------------------------------------------- #
def bootstrap_ci(values: np.ndarray, n_boot: int, rng: np.random.Generator,
                 weights: np.ndarray | None = None) -> tuple[float, float]:
    n = len(values)
    idx = rng.integers(0, n, size=(n_boot, n))
    if weights is None:
        stats = values[idx].mean(axis=1)
    else:
        w = weights[idx]
        stats = (values[idx] * w).sum(axis=1) / w.sum(axis=1)
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


# --------------------------------------------------------------------------- #
# GroupKFold CV + SMOTE 内部                                                   #
# --------------------------------------------------------------------------- #
def cross_val_evaluate(
    model_cls,
    model_params: dict,
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    classes: list[str],
    n_splits: int,
    smote_k: int,
    smote_fallback_n: int,
    seed: int,
) -> dict:
    """GroupKFold CV with SMOTE inside each fold.

    Returns dict with keys: cv_accuracy (array), cv_f1 (array), cv_logloss (array).
    """
    gkf = GroupKFold(n_splits=n_splits)
    accs, f1s, lls = [], [], []

    for fold_i, (tr_idx, va_idx) in enumerate(gkf.split(X, y, groups)):
        X_tr, y_tr = X[tr_idx], y[tr_idx]
        X_va, y_va = X[va_idx], y[va_idx]

        # SMOTE inside fold
        X_tr_r, y_tr_r = resample_training_fold(X_tr, y_tr, smote_k, smote_fallback_n,
                                                  rng_seed=seed + fold_i)

        model = model_cls(**model_params, random_state=seed)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X_tr_r, y_tr_r)

        y_pred = model.predict(X_va)
        accs.append(accuracy_score(y_va, y_pred))
        f1s.append(f1_score(y_va, y_pred, average="macro", zero_division=0,
                            labels=classes))

        try:
            prob = model.predict_proba(X_va)
            proba_classes = list(model.classes_)
            # align to full class list
            proba_aligned = np.zeros((len(y_va), len(classes)))
            for ci, cls in enumerate(classes):
                if cls in proba_classes:
                    proba_aligned[:, ci] = prob[:, proba_classes.index(cls)]
            proba_aligned = np.clip(proba_aligned, 1e-10, 1)
            proba_aligned /= proba_aligned.sum(axis=1, keepdims=True)
            lls.append(log_loss(y_va, proba_aligned, labels=classes))
        except Exception:
            lls.append(np.nan)

    return {
        "cv_accuracy": np.array(accs),
        "cv_f1": np.array(f1s),
        "cv_logloss": np.array(lls),
    }


def cross_val_evaluate_catboost(
    model_cls,
    model_params: dict,
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    classes: list[str],
    n_splits: int,
    smote_k: int,
    smote_fallback_n: int,
    seed: int,
) -> dict:
    """Same as cross_val_evaluate but CatBoost uses random_seed instead of random_state."""
    gkf = GroupKFold(n_splits=n_splits)
    accs, f1s, lls = [], [], []

    for fold_i, (tr_idx, va_idx) in enumerate(gkf.split(X, y, groups)):
        X_tr, y_tr = X[tr_idx], y[tr_idx]
        X_va, y_va = X[va_idx], y[va_idx]

        X_tr_r, y_tr_r = resample_training_fold(X_tr, y_tr, smote_k, smote_fallback_n,
                                                  rng_seed=seed + fold_i)

        params = dict(model_params)
        params["random_seed"] = seed + fold_i
        model = model_cls(**params)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X_tr_r, y_tr_r)

        y_pred = model.predict(X_va)
        if isinstance(y_pred[0], (list, np.ndarray)):
            y_pred = np.array([p[0] for p in y_pred])
        y_pred = y_pred.astype(str)

        accs.append(accuracy_score(y_va, y_pred))
        f1s.append(f1_score(y_va, y_pred, average="macro", zero_division=0,
                            labels=classes))

        try:
            prob = model.predict_proba(X_va)
            proba_classes = list(model.classes_)
            proba_aligned = np.zeros((len(y_va), len(classes)))
            for ci, cls in enumerate(classes):
                if cls in proba_classes:
                    proba_aligned[:, ci] = prob[:, proba_classes.index(cls)]
            proba_aligned = np.clip(proba_aligned, 1e-10, 1)
            proba_aligned /= proba_aligned.sum(axis=1, keepdims=True)
            lls.append(log_loss(y_va, proba_aligned, labels=classes))
        except Exception:
            lls.append(np.nan)

    return {
        "cv_accuracy": np.array(accs),
        "cv_f1": np.array(f1s),
        "cv_logloss": np.array(lls),
    }


# --------------------------------------------------------------------------- #
# 特征重要性                                                                    #
# --------------------------------------------------------------------------- #
def get_feature_importance(model, feature_names: list[str],
                           model_name: str) -> pd.DataFrame:
    """Extract and normalise feature importances."""
    if model_name == "catboost":
        imp = model.get_feature_importance()
    else:
        imp = model.feature_importances_
    imp = np.array(imp, dtype=float)
    imp = imp / imp.sum()
    df = pd.DataFrame({"feature": feature_names, "importance": imp})
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 图表输出                                                                      #
# --------------------------------------------------------------------------- #
def plot_feature_importance_comparison(
    rf_imp: pd.DataFrame, xgb_imp: pd.DataFrame, cat_imp: pd.DataFrame,
    top_n: int, out_path: str,
) -> None:
    """三模型特征重要性并列图 (Yuqian Fig. 3 风格)。"""
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use("Agg")

    # Use top-N union of features across all three models
    top_feats = set()
    for df in (rf_imp, xgb_imp, cat_imp):
        top_feats.update(df.head(top_n)["feature"].tolist())
    top_feats = list(top_feats)

    def get_val(df, feat):
        row = df[df["feature"] == feat]
        return float(row["importance"].iloc[0]) if len(row) else 0.0

    rf_vals = [get_val(rf_imp, f) for f in top_feats]
    xgb_vals = [get_val(xgb_imp, f) for f in top_feats]
    cat_vals = [get_val(cat_imp, f) for f in top_feats]

    order = np.argsort(rf_vals)[::-1]
    feats_sorted = [top_feats[i] for i in order]
    rf_sorted = [rf_vals[i] for i in order]
    xgb_sorted = [xgb_vals[i] for i in order]
    cat_sorted = [cat_vals[i] for i in order]

    x = np.arange(len(feats_sorted))
    w = 0.25
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x - w, rf_sorted, w, label="Random Forest", color="#2196F3")
    ax.bar(x, xgb_sorted, w, label="XGBoost", color="#FF9800")
    ax.bar(x + w, cat_sorted, w, label="CatBoost", color="#4CAF50")
    ax.set_xticks(x)
    ax.set_xticklabels(feats_sorted, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Feature importance (normalised)")
    ax.set_title("B3: Feature importance — RF vs XGBoost vs CatBoost")
    ax.legend()
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_confusion_matrix(cm: np.ndarray, classes: list[str], out_path: str,
                          title: str = "Confusion Matrix") -> None:
    """Normalised confusion matrix heatmap."""
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use("Agg")

    cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True).clip(min=1)
    fig, ax = plt.subplots(figsize=(max(8, len(classes)), max(6, len(classes) - 2)))
    im = ax.imshow(cm_norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(np.arange(len(classes)))
    ax.set_yticks(np.arange(len(classes)))
    ax.set_xticklabels(classes, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(classes, fontsize=7)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    for i in range(len(classes)):
        for j in range(len(classes)):
            val = cm_norm[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=6, color="white" if val > 0.5 else "black")
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_probability_gmm(probs: np.ndarray, out_path: str, model_name: str) -> None:
    """Max-class probability distribution + GMM fit (AIC/BIC for k=1..5)."""
    import matplotlib.pyplot as plt
    import matplotlib
    from sklearn.mixture import GaussianMixture
    matplotlib.use("Agg")

    probs = probs.clip(1e-4, 1 - 1e-4)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    axes[0].hist(probs, bins=50, color="#2196F3", alpha=0.7, edgecolor="white")
    axes[0].set_xlabel("Max-class probability")
    axes[0].set_ylabel("Count")
    axes[0].set_title(f"{model_name}: Confidence distribution")
    axes[0].spines[["top", "right"]].set_visible(False)

    X_gmm = probs.reshape(-1, 1)
    aics, bics, ks = [], [], list(range(1, 6))
    for k in ks:
        gm = GaussianMixture(n_components=k, random_state=42)
        gm.fit(X_gmm)
        aics.append(gm.aic(X_gmm))
        bics.append(gm.bic(X_gmm))

    axes[1].plot(ks, aics, "o-", label="AIC", color="#F44336")
    axes[1].plot(ks, bics, "s--", label="BIC", color="#9C27B0")
    axes[1].set_xlabel("k (GMM components)")
    axes[1].set_ylabel("Information criterion")
    axes[1].set_title("GMM AIC/BIC (k=1..5)")
    axes[1].legend()
    axes[1].spines[["top", "right"]].set_visible(False)

    plt.suptitle(f"B3 {model_name}: citywide confidence analysis", y=1.02)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()

    return {"ks": ks, "aic": aics, "bic": bics}

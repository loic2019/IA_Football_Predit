"""
ml_models/deep_model.py — Petit réseau de neurones (PyTorch)
==================================================================
Architecture volontairement modeste : ~4000 matchs d'entraînement ne
justifient pas un réseau à 50 couches (surapprentissage quasi garanti). Ce
réseau a 6 couches denses (12 → 64 → 64 → 32 → 16 → 8 → 3), avec dropout et
batch norm, et s'arrête tôt (early stopping) sur un jeu de validation — c'est
la version "honnête" du deep learning pour ce volume de données.

À mesure que la base grandit (scraping continu), les couches/tailles peuvent
être augmentées sans tout réécrire — mais il n'y a aucun intérêt à le faire
avant d'avoir au moins quelques dizaines de milliers de matchs.
"""

from pathlib import Path

import numpy as np

from ml_models.model_cache import get_cached

MODEL_PATH = Path("ml_models/weights/deep_model.pt")
SCALER_PATH = Path("ml_models/weights/deep_scaler.json")


class DeepMatchNet:
    """Wrapper autour du nn.Module — importe torch en lazy pour ne jamais
    faire planter le reste de l'app si torch n'est pas installé.

    `depth_profile` choisit l'architecture parmi 3 candidats (voir train()) :
    - "shallow" : 3 couches (12→32→16→3)
    - "medium"  : 6 couches (12→64→64→32→16→8→3) — profondeur par défaut historique
    - "deep"    : 9 couches (12→128→128→96→64→48→32→16→8→3) — le maximum
      raisonnable pour quelques milliers de lignes ; au-delà, le risque de
      surapprentissage dépasse largement le gain potentiel.
    """

    PROFILES = ("shallow", "medium", "deep")

    def __init__(self, input_dim: int, depth_profile: str = "medium"):
        import torch.nn as nn

        def _block(in_f, out_f, dropout):
            return [nn.Linear(in_f, out_f), nn.BatchNorm1d(out_f), nn.ReLU(), nn.Dropout(dropout)]

        if depth_profile == "shallow":
            layers = _block(input_dim, 32, 0.2) + _block(32, 16, 0.2) + [nn.Linear(16, 3)]
        elif depth_profile == "deep":
            layers = (
                _block(input_dim, 128, 0.4) + _block(128, 128, 0.4) + _block(128, 96, 0.3)
                + _block(96, 64, 0.3) + _block(64, 48, 0.2) + _block(48, 32, 0.2)
                + [nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 8), nn.ReLU(), nn.Linear(8, 3)]
            )
        else:  # medium (par défaut)
            layers = (
                _block(input_dim, 64, 0.3) + _block(64, 64, 0.3) + _block(64, 32, 0.2)
                + [nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 8), nn.ReLU(), nn.Linear(8, 3)]
            )

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(*layers)

            def forward(self, x):
                return self.net(x)

        self.module = _Net()

    def parameters(self):
        return self.module.parameters()


def _standardize_fit(X: np.ndarray) -> tuple:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-6] = 1.0
    return mean, std


def _train_one_profile(profile: str, X_train, y_train, X_val, y_val, input_dim, epochs, patience, device):
    """Entraîne UNE architecture candidate et renvoie (state_dict, val_acc, val_loss, epochs_run)."""
    import torch
    import torch.nn as nn

    net = DeepMatchNet(input_dim=input_dim, depth_profile=profile).module.to(device)
    optimizer = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=5)
    criterion = nn.CrossEntropyLoss()

    best_val_loss = float("inf")
    best_state = None
    epochs_without_improvement = 0
    epochs_run = 0

    for epoch in range(epochs):
        net.train()
        optimizer.zero_grad()
        loss = criterion(net(X_train), y_train)
        loss.backward()
        optimizer.step()

        net.eval()
        with torch.no_grad():
            val_loss = criterion(net(X_val), y_val).item()
        scheduler.step(val_loss)

        epochs_run = epoch + 1
        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break

    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        train_acc = (net(X_train).argmax(dim=1) == y_train).float().mean().item()
        val_acc = (net(X_val).argmax(dim=1) == y_val).float().mean().item()

    return best_state, val_acc, best_val_loss, epochs_run, train_acc


def train(X: np.ndarray, y: np.ndarray, epochs: int = 200, patience: int = 15) -> dict:
    """
    Entraîne 3 architectures candidates (shallow/medium/deep — voir
    DeepMatchNet) et garde automatiquement celle qui généralise le mieux sur
    le jeu de validation. C'est la version honnête de "profondeur choisie
    automatiquement" : pas une profondeur fixe imposée (ex. 10 couches), mais
    une sélection empirique parmi des architectures raisonnables pour le
    volume de données réel.

    Utilise AdamW + ReduceLROnPlateau (learning rate scheduler), et le GPU
    si disponible (torch.cuda.is_available()), sinon CPU (aucune erreur).
    """
    import torch
    import json

    if len(X) < 40:
        return {"trained": False, "reason": "Pas assez de données (minimum 40 matchs pour un split train/val)."}

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    mean, std = _standardize_fit(X)
    X_norm = (X - mean) / std

    n = len(X_norm)
    idx = np.random.RandomState(42).permutation(n)
    split = max(1, int(n * 0.8))
    train_idx, val_idx = idx[:split], idx[split:]
    if len(val_idx) == 0:
        val_idx = train_idx[-max(1, n // 10):]

    X_train = torch.tensor(X_norm[train_idx], dtype=torch.float32, device=device)
    y_train = torch.tensor(y[train_idx], dtype=torch.long, device=device)
    X_val = torch.tensor(X_norm[val_idx], dtype=torch.float32, device=device)
    y_val = torch.tensor(y[val_idx], dtype=torch.long, device=device)

    candidates = {}
    for profile in DeepMatchNet.PROFILES:
        state, val_acc, val_loss, epochs_run, train_acc = _train_one_profile(
            profile, X_train, y_train, X_val, y_val, X.shape[1], epochs, patience, device
        )
        candidates[profile] = {
            "state": state, "val_acc": val_acc, "val_loss": val_loss,
            "epochs_run": epochs_run, "train_acc": train_acc,
        }

    best_profile = max(candidates, key=lambda p: candidates[p]["val_acc"])
    best = candidates[best_profile]

    torch.save(best["state"], MODEL_PATH)
    with open(SCALER_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "mean": mean.tolist(), "std": std.tolist(), "input_dim": int(X.shape[1]),
            "depth_profile": best_profile,
        }, f)

    return {
        "trained": True,
        "train_acc": round(best["train_acc"], 4),
        "val_acc": round(best["val_acc"], 4),
        "epochs_run": best["epochs_run"],
        "n_samples": n,
        "depth_profile_chosen": best_profile,
        "device": str(device),
        "candidates_val_acc": {p: round(c["val_acc"], 4) for p, c in candidates.items()},
    }


def is_trained() -> bool:
    return MODEL_PATH.exists() and SCALER_PATH.exists()


def predict_proba(X: np.ndarray) -> np.ndarray:
    """Renvoie les probabilités (n, 3) [P(1), P(X), P(2)]. Suppose is_trained() == True."""
    import torch
    import torch.nn.functional as F

    def _load():
        import json

        with open(SCALER_PATH, encoding="utf-8") as f:
            scaler = json.load(f)
        mean = np.array(scaler["mean"], dtype=np.float32)
        std = np.array(scaler["std"], dtype=np.float32)
        input_dim = scaler["input_dim"]
        depth_profile = scaler.get("depth_profile", "medium")  # retro-compatible avec d'anciens poids

        net = DeepMatchNet(input_dim=input_dim, depth_profile=depth_profile).module
        net.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
        net.eval()
        return net, mean, std

    # Mis en cache par mtime de MODEL_PATH (SCALER_PATH est toujours réécrit
    # en même temps que MODEL_PATH par train(), donc un seul mtime suffit).
    net, mean, std = get_cached(MODEL_PATH, _load)

    X_norm = (X - mean) / std
    with torch.no_grad():
        logits = net(torch.tensor(X_norm, dtype=torch.float32))
        probs = F.softmax(logits, dim=1).numpy()
    return probs


def get_chosen_profile() -> str:
    """Pour affichage (admin/stats) : quelle profondeur a été retenue au dernier entraînement."""
    import json
    if not SCALER_PATH.exists():
        return "non entraîné"
    with open(SCALER_PATH, encoding="utf-8") as f:
        return json.load(f).get("depth_profile", "medium")

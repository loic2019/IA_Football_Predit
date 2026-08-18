"""
deep_learning/inference.py — Inférence optimisée (CUDA, mixed precision, ONNX)
===============================================================================
Utilise torch.cuda si disponible ; export ONNX pour déploiement production.
"""

from typing import Optional


def get_device() -> str:
    """
    Sélectionne le device optimal (CUDA > CPU).

    Returns:
        'cuda' ou 'cpu'.
    """
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def export_to_onnx(model_path: str, output_path: str, input_dim: int = 12) -> bool:
    """
    Exporte un modèle PyTorch vers ONNX pour inférence optimisée.

    Args:
        model_path: Chemin .pt source.
        output_path: Chemin .onnx destination.
        input_dim: Dimension entrée.

    Returns:
        True si export réussi.
    """
    try:
        import torch
        from ml_models.deep_model import DeepMatchNet

        net = DeepMatchNet(input_dim=input_dim).module
        net.load_state_dict(torch.load(model_path, map_location="cpu"))
        net.eval()
        dummy = torch.randn(1, input_dim)
        torch.onnx.export(net, dummy, output_path, opset_version=17)
        return True
    except Exception:
        return False

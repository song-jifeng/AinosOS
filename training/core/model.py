"""
Model base class and utilities for the Ainos training framework.

This module provides the abstract base class for all models in the framework,
along with helper functions for parameter counting, device management, and
model initialization.
"""

from __future__ import annotations

import abc
import logging
import math
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.init as init

logger = logging.getLogger(__name__)


def count_parameters(model: nn.Module, only_trainable: bool = True) -> int:
    """Count the number of parameters in a model.

    Args:
        model: The PyTorch model.
        only_trainable: If True, only count trainable parameters.

    Returns:
        Total number of parameters.
    """
    if only_trainable:
        return sum(p.numel() for p in model.parameters() if p.requires_grad)
    return sum(p.numel() for p in model.parameters())


def count_parameters_by_layer(model: nn.Module) -> Dict[str, int]:
    """Count parameters grouped by layer name.

    Args:
        model: The PyTorch model.

    Returns:
        Dictionary mapping layer names to parameter counts.
    """
    counts: Dict[str, int] = {}
    for name, param in model.named_parameters():
        layer_name = name.rsplit(".", 1)[0] if "." in name else name
        counts[layer_name] = counts.get(layer_name, 0) + param.numel()
    return counts


def get_device(model: nn.Module) -> torch.device:
    """Get the device of a model's first parameter.

    Args:
        model: The PyTorch model.

    Returns:
        The device of the model.

    Raises:
        RuntimeError: If the model has no parameters.
    """
    try:
        param = next(model.parameters())
        return param.device
    except StopIteration:
        raise RuntimeError("Model has no parameters, cannot determine device.")


def get_dtype(model: nn.Module) -> torch.dtype:
    """Get the dtype of a model's first parameter.

    Args:
        model: The PyTorch model.

    Returns:
        The dtype of the model.

    Raises:
        RuntimeError: If the model has no parameters.
    """
    try:
        param = next(model.parameters())
        return param.dtype
    except StopIteration:
        raise RuntimeError("Model has no parameters, cannot determine dtype.")


def freeze_model(model: nn.Module, freeze: bool = True) -> nn.Module:
    """Freeze or unfreeze all model parameters.

    Args:
        model: The PyTorch model.
        freeze: If True, freeze all parameters; otherwise unfreeze.

    Returns:
        The model with updated requires_grad settings.
    """
    for param in model.parameters():
        param.requires_grad = not freeze
    return model


def freeze_layers(
    model: nn.Module,
    layer_names: List[str],
    freeze: bool = True,
    match_substring: bool = True,
) -> nn.Module:
    """Freeze or unfreeze specific layers by name.

    Args:
        model: The PyTorch model.
        layer_names: List of layer names (or substrings) to freeze/unfreeze.
        freeze: If True, freeze; otherwise unfreeze.
        match_substring: If True, match layer names as substrings.

    Returns:
        The model with updated requires_grad settings.
    """
    for name, param in model.named_parameters():
        should_freeze = False
        for layer_name in layer_names:
            if match_substring:
                if layer_name in name:
                    should_freeze = True
                    break
            else:
                if name == layer_name or name.startswith(layer_name + "."):
                    should_freeze = True
                    break
        if should_freeze:
            param.requires_grad = not freeze
    return model


def get_parameter_groups(
    model: nn.Module,
    weight_decay: float = 0.01,
    no_decay_names: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Split model parameters into groups with and without weight decay.

    Args:
        model: The PyTorch model.
        weight_decay: Weight decay value for the decay group.
        no_decay_names: Layer name substrings that should not have weight decay.
            Defaults to common names like 'bias', 'LayerNorm', 'layernorm'.

    Returns:
        List of parameter group dictionaries for the optimizer.
    """
    if no_decay_names is None:
        no_decay_names = ["bias", "LayerNorm", "layernorm", "layer_norm", "ln"]

    decay_params: List[nn.Parameter] = []
    no_decay_params: List[nn.Parameter] = []

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if any(nd in name for nd in no_decay_names):
            no_decay_params.append(param)
        else:
            decay_params.append(param)

    groups: List[Dict[str, Any]] = [
        {"params": decay_params, "weight_decay": weight_decay},
        {"params": no_decay_params, "weight_decay": 0.0},
    ]
    return groups


def get_model_size(model: nn.Module, unit: str = "MB") -> float:
    """Estimate the memory size of the model parameters.

    Args:
        model: The PyTorch model.
        unit: The unit for the result ('B', 'KB', 'MB', 'GB').

    Returns:
        Estimated size of the model parameters.

    Raises:
        ValueError: If the unit is not recognized.
    """
    total_bytes = sum(p.numel() * p.element_size() for p in model.parameters())

    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    if unit.upper() not in units:
        raise ValueError(f"Unknown unit: {unit}. Use one of {list(units.keys())}")

    return total_bytes / units[unit.upper()]


def print_model_summary(
    model: nn.Module,
    show_layers: bool = True,
    show_parameters: bool = True,
    show_size: bool = True,
) -> None:
    """Print a summary of the model architecture.

    Args:
        model: The PyTorch model.
        show_layers: If True, print layer-by-layer information.
        show_parameters: If True, print parameter counts.
        show_size: If True, print estimated model size.
    """
    print("=" * 80)
    print(f"Model: {model.__class__.__name__}")
    print("=" * 80)

    if show_layers:
        total_params = 0
        for name, module in model.named_modules():
            if list(module.children()):
                continue  # Skip parent modules, only show leaves
            params = sum(p.numel() for p in module.parameters())
            if params > 0:
                trainable = sum(
                    p.numel() for p in module.parameters() if p.requires_grad
                )
                print(
                    f"  {name:60s} | Params: {params:>10,} "
                    f"| Trainable: {trainable:>10,}"
                )
                total_params += params
        print("-" * 80)

    if show_parameters:
        total = count_parameters(model, only_trainable=False)
        trainable = count_parameters(model, only_trainable=True)
        print(f"Total parameters:     {total:>12,}")
        print(f"Trainable parameters: {trainable:>12,}")
        print(f"Non-trainable:        {total - trainable:>12,}")

    if show_size:
        size_mb = get_model_size(model, "MB")
        print(f"Estimated model size: {size_mb:>10.2f} MB")

    print("=" * 80)


def init_weights(
    module: nn.Module,
    mode: str = "normal",
    gain: float = 1.0,
    seed: Optional[int] = None,
) -> None:
    """Initialize weights of a module using a specified method.

    Args:
        module: The PyTorch module to initialize.
        mode: Initialization method ('normal', 'xavier_normal', 'xavier_uniform',
            'kaiming_normal', 'kaiming_uniform', 'orthogonal', 'zeros', 'ones').
        gain: Gain factor for initialization.
        seed: Optional random seed for reproducibility.

    Raises:
        ValueError: If the mode is not recognized.
    """
    if seed is not None:
        torch.manual_seed(seed)

    if isinstance(module, (nn.Linear, nn.Conv1d, nn.Conv2d, nn.Conv3d)):
        if mode == "normal":
            init.normal_(module.weight, mean=0.0, std=gain / math.sqrt(module.weight.size(1)))
        elif mode == "xavier_normal":
            init.xavier_normal_(module.weight, gain=gain)
        elif mode == "xavier_uniform":
            init.xavier_uniform_(module.weight, gain=gain)
        elif mode == "kaiming_normal":
            init.kaiming_normal_(module.weight, a=0.0, mode="fan_in", nonlinearity="leaky_relu")
        elif mode == "kaiming_uniform":
            init.kaiming_uniform_(module.weight, a=math.sqrt(5), mode="fan_in", nonlinearity="leaky_relu")
        elif mode == "orthogonal":
            init.orthogonal_(module.weight, gain=gain)
        elif mode == "zeros":
            init.zeros_(module.weight)
        elif mode == "ones":
            init.ones_(module.weight)
        else:
            raise ValueError(f"Unknown initialization mode: {mode}")

        if module.bias is not None:
            init.zeros_(module.bias)

    elif isinstance(module, (nn.Embedding,)):
        if mode == "normal":
            init.normal_(module.weight, mean=0.0, std=1.0)
        elif mode == "xavier_uniform":
            init.xavier_uniform_(module.weight, gain=gain)
        elif mode == "zeros":
            init.zeros_(module.weight)

    elif isinstance(module, (nn.LayerNorm, nn.BatchNorm1d, nn.BatchNorm2d, nn.BatchNorm3d)):
        if hasattr(module, "weight") and module.weight is not None:
            init.ones_(module.weight)
        if hasattr(module, "bias") and module.bias is not None:
            init.zeros_(module.bias)


def apply_init(
    model: nn.Module,
    mode: str = "normal",
    gain: float = 1.0,
    seed: Optional[int] = None,
) -> nn.Module:
    """Apply weight initialization to all modules in a model.

    Args:
        model: The PyTorch model.
        mode: Initialization method.
        gain: Gain factor.
        seed: Optional random seed.

    Returns:
        The model with initialized weights.
    """
    model.apply(lambda m: init_weights(m, mode=mode, gain=gain, seed=seed))
    return model


class BaseModel(nn.Module, abc.ABC):
    """Abstract base class for all models in the Ainos training framework.

    All models should inherit from this class and implement the forward method.
    This class provides common utilities for device management, saving/loading,
    and parameter counting.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the base model.

        Args:
            config: Optional configuration dictionary for the model.
        """
        super().__init__()
        self.config = config or {}
        self._device: Optional[torch.device] = None

    @abc.abstractmethod
    def forward(self, *args: Any, **kwargs: Any) -> Any:
        """Forward pass of the model.

        Args:
            *args: Positional arguments for the forward pass.
            **kwargs: Keyword arguments for the forward pass.

        Returns:
            The model output.
        """
        raise NotImplementedError

    @property
    def device(self) -> torch.device:
        """Get the device of the model."""
        if self._device is None:
            try:
                self._device = get_device(self)
            except RuntimeError:
                self._device = torch.device("cpu")
        return self._device

    @property
    def num_parameters(self) -> int:
        """Get the total number of parameters."""
        return count_parameters(self, only_trainable=False)

    @property
    def num_trainable_parameters(self) -> int:
        """Get the number of trainable parameters."""
        return count_parameters(self, only_trainable=True)

    def freeze(self) -> None:
        """Freeze all model parameters."""
        freeze_model(self, freeze=True)
        logger.info("All model parameters frozen.")

    def unfreeze(self) -> None:
        """Unfreeze all model parameters."""
        freeze_model(self, freeze=False)
        logger.info("All model parameters unfrozen.")

    def get_submodel(self, name: str) -> nn.Module:
        """Get a submodule by name.

        Args:
            name: The name of the submodule (dot-separated).

        Returns:
            The submodule.

        Raises:
            AttributeError: If the submodule is not found.
        """
        parts = name.split(".")
        module: nn.Module = self
        for part in parts:
            if not hasattr(module, part):
                raise AttributeError(f"Model has no attribute '{part}' in '{name}'")
            module = getattr(module, part)
        return module

    def summary(self) -> None:
        """Print a summary of the model."""
        print_model_summary(self)

    def save_pretrained(self, save_directory: Union[str, Path]) -> None:
        """Save the model weights and config to a directory.

        Args:
            save_directory: Path to the directory to save to.
        """
        save_path = Path(save_directory)
        save_path.mkdir(parents=True, exist_ok=True)

        # Save model weights
        torch.save(self.state_dict(), save_path / "pytorch_model.bin")

        # Save config
        import json
        if self.config:
            config_path = save_path / "config.json"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)

        logger.info(f"Model saved to {save_path}")

    @classmethod
    def from_pretrained(
        cls,
        pretrained_path: Union[str, Path],
        config: Optional[Dict[str, Any]] = None,
        map_location: Optional[Union[str, torch.device]] = None,
        strict: bool = True,
    ) -> BaseModel:
        """Load a model from a saved checkpoint.

        Args:
            pretrained_path: Path to the saved model directory.
            config: Optional config override. If None, loads from config.json.
            map_location: Device to map the model to.
            strict: Whether to strictly enforce that the keys in state_dict match.

        Returns:
            The loaded model.

        Raises:
            FileNotFoundError: If the checkpoint file doesn't exist.
        """
        load_path = Path(pretrained_path)

        # Load config if available and not provided
        if config is None:
            config_path = load_path / "config.json"
            if config_path.exists():
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

        # Instantiate model
        model = cls(config=config)

        # Load weights
        weights_path = load_path / "pytorch_model.bin"
        if not weights_path.exists():
            raise FileNotFoundError(f"Model weights not found at {weights_path}")

        state_dict = torch.load(weights_path, map_location=map_location)
        model.load_state_dict(state_dict, strict=strict)
        logger.info(f"Model loaded from {load_path}")

        return model

    def get_memory_footprint(self) -> Dict[str, float]:
        """Get memory footprint of the model in MB.

        Returns:
            Dictionary with memory information.
        """
        param_memory = get_model_size(self, "MB")
        buffer_memory = sum(
            buf.numel() * buf.element_size() for buf in self.buffers()
        ) / (1024**2)

        return {
            "parameters_mb": param_memory,
            "buffers_mb": buffer_memory,
            "total_mb": param_memory + buffer_memory,
        }

    def set_gradient_checkpointing(self, enabled: bool = True) -> None:
        """Enable or disable gradient checkpointing.

        Args:
            enabled: Whether to enable gradient checkpointing.
        """
        self.gradient_checkpointing_enabled = enabled
        logger.info(f"Gradient checkpointing {'enabled' if enabled else 'disabled'}.")

    def get_parameter_groups_for_optimizer(
        self,
        weight_decay: float = 0.01,
        no_decay_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get parameter groups for the optimizer.

        Args:
            weight_decay: Weight decay value.
            no_decay_names: Layer names that should not have weight decay.

        Returns:
            Parameter groups for the optimizer.
        """
        return get_parameter_groups(self, weight_decay, no_decay_names)


class ModuleList(nn.ModuleList):
    """A wrapper around nn.ModuleList with additional functionality."""

    def __init__(self, modules: Optional[List[nn.Module]] = None) -> None:
        """Initialize the module list.

        Args:
            modules: Optional list of modules.
        """
        super().__init__(modules if modules is not None else [])

    def forward(self, *args: Any, **kwargs: Any) -> List[Any]:
        """Apply all modules sequentially and collect outputs.

        Args:
            *args: Positional arguments passed to each module.
            **kwargs: Keyword arguments passed to each module.

        Returns:
            List of outputs from each module.
        """
        return [module(*args, **kwargs) for module in self]


class SequentialModule(nn.Sequential):
    """A wrapper around nn.Sequential with additional utilities."""

    def __init__(self, *modules: nn.Module) -> None:
        """Initialize the sequential module.

        Args:
            *modules: Modules to chain together.
        """
        super().__init__(*modules)

    def get_output_dim(self) -> Optional[int]:
        """Get the output dimension of the last module.

        Returns:
            Output dimension, or None if it cannot be determined.
        """
        last_module = self[-1] if len(self) > 0 else None
        if last_module is None:
            return None

        if isinstance(last_module, nn.Linear):
            return last_module.out_features
        return None
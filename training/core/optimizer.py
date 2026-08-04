"""
Optimizer module for the Ainos training framework.

Provides implementations and factory functions for popular optimizers
including Adam, AdamW, SGD, and Lion.
"""

from __future__ import annotations

import inspect
import logging
import math
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

import torch
import torch.nn as nn
from torch.optim.optimizer import Optimizer

logger = logging.getLogger(__name__)


class Lion(Optimizer):
    """Lion optimizer - EvoLved Sign Momentum.

    As described in https://arxiv.org/abs/2302.06675.

    The Lion optimizer uses the sign of the momentum update, which can be
    more memory-efficient than Adam.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-4.
        betas: Coefficients for computing running averages of gradient and its square.
            Default: (0.9, 0.99).
        weight_decay: Weight decay coefficient. Default: 0.0.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-4,
        betas: Tuple[float, float] = (0.9, 0.99),
        weight_decay: float = 0.0,
    ) -> None:
        """Initialize the Lion optimizer.

        Args:
            params: Iterable of parameters to optimize or dicts defining parameter groups.
            lr: Learning rate.
            betas: Coefficients for momentum.
            weight_decay: Weight decay factor.

        Raises:
            ValueError: If betas are not in range [0, 1).
        """
        if not 0.0 <= lr:
            raise ValueError(f"Invalid learning rate: {lr}")
        if not 0.0 <= betas[0] < 1.0:
            raise ValueError(f"Invalid beta parameter at index 0: {betas[0]}")
        if not 0.0 <= betas[1] < 1.0:
            raise ValueError(f"Invalid beta parameter at index 1: {betas[1]}")
        if not 0.0 <= weight_decay:
            raise ValueError(f"Invalid weight_decay value: {weight_decay}")

        defaults = dict(lr=lr, betas=betas, weight_decay=weight_decay)
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            lr = group["lr"]
            beta1, beta2 = group["betas"]
            weight_decay = group["weight_decay"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]

                # State initialization
                if len(state) == 0:
                    state["exp_avg"] = torch.zeros_like(p.data)

                exp_avg = state["exp_avg"]

                # Update momentum
                exp_avg.mul_(beta1).add_(grad, alpha=1.0 - beta1)

                # Apply weight decay
                if weight_decay > 0.0:
                    p.data.mul_(1.0 - lr * weight_decay)

                # Update parameters (sign of momentum)
                update = exp_avg.sign()
                p.data.add_(update, alpha=-lr)

                # Update beta2 EMA (for tracking)
                exp_avg.mul_(beta2).add_(grad, alpha=1.0 - beta2)

        return loss


class AdamWag(Optimizer):
    """AdamW with optional weight averaging group.

    A variant of AdamW with additional features for grouped parameter handling.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        betas: Tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.01,
        amsgrad: bool = False,
    ) -> None:
        """Initialize AdamWag optimizer.

        Args:
            params: Model parameters or parameter groups.
            lr: Learning rate.
            betas: Coefficients for running averages.
            eps: Term for numerical stability.
            weight_decay: Weight decay factor.
            amsgrad: Whether to use AMSGrad variant.
        """
        defaults = dict(
            lr=lr,
            betas=betas,
            eps=eps,
            weight_decay=weight_decay,
            amsgrad=amsgrad,
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            params_with_grad = []
            grads = []
            exp_avgs = []
            exp_avg_sqs = []
            max_exp_avg_sqs = []
            state_steps = []

            for p in group["params"]:
                if p.grad is None:
                    continue
                params_with_grad.append(p)
                grads.append(p.grad)

                state = self.state[p]
                if len(state) == 0:
                    state["step"] = 0
                    state["exp_avg"] = torch.zeros_like(p.data)
                    state["exp_avg_sq"] = torch.zeros_like(p.data)
                    if group["amsgrad"]:
                        state["max_exp_avg_sq"] = torch.zeros_like(p.data)

                exp_avgs.append(state["exp_avg"])
                exp_avg_sqs.append(state["exp_avg_sq"])

                if group["amsgrad"]:
                    max_exp_avg_sqs.append(state["max_exp_avg_sq"])

                state_steps.append(state["step"])

            beta1, beta2 = group["betas"]

            self._adamw_update(
                params_with_grad,
                grads,
                exp_avgs,
                exp_avg_sqs,
                max_exp_avg_sqs if group["amsgrad"] else None,
                state_steps,
                beta1=beta1,
                beta2=beta2,
                lr=group["lr"],
                weight_decay=group["weight_decay"],
                eps=group["eps"],
                amsgrad=group["amsgrad"],
            )

            for s in state_steps:
                s += 1

        return loss

    @staticmethod
    def _adamw_update(
        params: List[nn.Parameter],
        grads: List[torch.Tensor],
        exp_avgs: List[torch.Tensor],
        exp_avg_sqs: List[torch.Tensor],
        max_exp_avg_sqs: Optional[List[torch.Tensor]],
        state_steps: List[int],
        beta1: float,
        beta2: float,
        lr: float,
        weight_decay: float,
        eps: float,
        amsgrad: bool,
    ) -> None:
        """Apply AdamW update step.

        Args:
            params: Parameters to update.
            grads: Gradients.
            exp_avgs: Exponential moving average of gradients.
            exp_avg_sqs: Exponential moving average of squared gradients.
            max_exp_avg_sqs: Maximum of exp_avg_sqs (for AMSGrad).
            state_steps: Number of steps taken.
            beta1: Beta1 coefficient.
            beta2: Beta2 coefficient.
            lr: Learning rate.
            weight_decay: Weight decay coefficient.
            eps: Numerical stability term.
            amsgrad: Whether to use AMSGrad.
        """
        for i, param in enumerate(params):
            grad = grads[i]
            exp_avg = exp_avgs[i]
            exp_avg_sq = exp_avg_sqs[i]
            step = state_steps[i]

            # Update step
            step += 1

            # Decay the first and second moment running average coefficient
            exp_avg.mul_(beta1).add_(grad, alpha=1 - beta1)
            exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

            if amsgrad and max_exp_avg_sqs is not None:
                torch.maximum(max_exp_avg_sqs[i], exp_avg_sq, out=max_exp_avg_sqs[i])
                denom = max_exp_avg_sqs[i].sqrt().add_(eps)
            else:
                denom = exp_avg_sq.sqrt().add_(eps)

            bias_correction1 = 1 - beta1**step
            bias_correction2 = 1 - beta2**step
            step_size = lr / bias_correction1

            # Apply weight decay
            if weight_decay > 0:
                param.data.mul_(1 - lr * weight_decay)

            # Apply update
            param.data.addcdiv_(exp_avg, denom, value=-step_size * bias_correction2**0.5)


class SophiaG(Optimizer):
    """SophiaG optimizer - a second-order optimizer.

    As described in https://arxiv.org/abs/2305.14342.

    Uses a diagonal Hessian estimate for preconditioning.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-4.
        betas: Coefficients for computing running averages. Default: (0.9, 0.95).
        rho: Clipping threshold. Default: 0.04.
        weight_decay: Weight decay coefficient. Default: 0.0.
        eps: Term for numerical stability. Default: 1e-8.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-4,
        betas: Tuple[float, float] = (0.9, 0.95),
        rho: float = 0.04,
        weight_decay: float = 0.0,
        eps: float = 1e-8,
    ) -> None:
        """Initialize SophiaG optimizer.

        Args:
            params: Model parameters.
            lr: Learning rate.
            betas: Momentum coefficients.
            rho: Clipping threshold.
            weight_decay: Weight decay.
            eps: Numerical stability.
        """
        defaults = dict(
            lr=lr, betas=betas, rho=rho, weight_decay=weight_decay, eps=eps
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            lr = group["lr"]
            rho = group["rho"]
            weight_decay = group["weight_decay"]
            eps = group["eps"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]

                if len(state) == 0:
                    state["step"] = 0
                    state["m"] = torch.zeros_like(p.data)
                    state["h"] = torch.zeros_like(p.data)

                m, h = state["m"], state["h"]
                step = state["step"] + 1

                # Update momentum
                m.mul_(beta1).add_(grad, alpha=1 - beta1)

                # Update Hessian estimate (using gradient squared)
                h.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

                # Bias correction
                m_hat = m / (1 - beta1**step)
                h_hat = h / (1 - beta2**step)

                # Apply weight decay
                if weight_decay > 0:
                    p.data.mul_(1 - lr * weight_decay)

                # Sophia update with clipping
                ratio = m_hat / (h_hat + eps).clamp(min=eps)
                clipped = ratio.clamp(-rho, rho)
                p.data.add_(clipped, alpha=-lr)

                state["step"] = step

        return loss


class LAMB(Optimizer):
    """LAMB optimizer - Layer-wise Adaptive Moments optimizer for Batch training.

    As described in https://arxiv.org/abs/1904.00962.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-3.
        betas: Coefficients for running averages. Default: (0.9, 0.999).
        eps: Term for numerical stability. Default: 1e-8.
        weight_decay: Weight decay coefficient. Default: 0.0.
        adam: Whether to use Adam-style update. Default: True.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        betas: Tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
        adam: bool = True,
    ) -> None:
        """Initialize LAMB optimizer.

        Args:
            params: Model parameters.
            lr: Learning rate.
            betas: Momentum coefficients.
            eps: Numerical stability.
            weight_decay: Weight decay.
            adam: Use Adam-style update (True) or SGD-style (False).
        """
        defaults = dict(
            lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, adam=adam
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]

                if len(state) == 0:
                    state["step"] = 0
                    state["exp_avg"] = torch.zeros_like(p.data)
                    state["exp_avg_sq"] = torch.zeros_like(p.data)

                exp_avg, exp_avg_sq = state["exp_avg"], state["exp_avg_sq"]
                beta1, beta2 = group["betas"]
                step = state["step"] + 1

                # Update moments
                exp_avg.mul_(beta1).add_(grad, alpha=1 - beta1)
                exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

                # Bias correction
                bias_correction1 = 1 - beta1**step
                bias_correction2 = 1 - beta2**step

                # Adam update
                adam_step = exp_avg / bias_correction1
                adam_step = adam_step / (exp_avg_sq / bias_correction2).sqrt().add_(
                    group["eps"]
                )

                # Apply weight decay
                if group["weight_decay"] > 0:
                    adam_step.add_(p.data, alpha=group["weight_decay"])

                # Trust ratio
                w_norm = p.data.norm(2.0)
                g_norm = adam_step.norm(2.0)

                if w_norm > 0 and g_norm > 0:
                    trust_ratio = w_norm / g_norm
                else:
                    trust_ratio = 1.0

                # Update
                p.data.add_(adam_step, alpha=-group["lr"] * trust_ratio)
                state["step"] = step

        return loss


class AdaFactor(Optimizer):
    """AdaFactor optimizer - memory-efficient adaptive optimizer.

    As described in https://arxiv.org/abs/1804.04235.

    Uses factored second-order moments for memory efficiency.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-3.
        beta1: Coefficient for first moment. Default: 0.9.
        beta2: Coefficient for second moment. Default: 0.999.
        eps1: Term for numerical stability for first moment. Default: 1e-30.
        eps2: Term for numerical stability for second moment. Default: 1e-3.
        clip_threshold: Threshold for gradient clipping. Default: 1.0.
        weight_decay: Weight decay coefficient. Default: 0.0.
        scale_parameter: Whether to scale the learning rate. Default: True.
        relative_step: Whether to use relative step size. Default: True.
        warmup_init: Whether to use warmup initialization. Default: False.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        beta1: float = 0.9,
        beta2: float = 0.999,
        eps1: float = 1e-30,
        eps2: float = 1e-3,
        clip_threshold: float = 1.0,
        weight_decay: float = 0.0,
        scale_parameter: bool = True,
        relative_step: bool = True,
        warmup_init: bool = False,
    ) -> None:
        """Initialize AdaFactor optimizer.

        Args:
            params: Model parameters.
            lr: Learning rate.
            beta1: First moment decay.
            beta2: Second moment decay.
            eps1: First moment epsilon.
            eps2: Second moment epsilon.
            clip_threshold: Gradient clipping threshold.
            weight_decay: Weight decay.
            scale_parameter: Scale learning rate by parameter norm.
            relative_step: Use relative step size.
            warmup_init: Use warmup initialization.
        """
        defaults = dict(
            lr=lr,
            beta1=beta1,
            beta2=beta2,
            eps1=eps1,
            eps2=eps2,
            clip_threshold=clip_threshold,
            weight_decay=weight_decay,
            scale_parameter=scale_parameter,
            relative_step=relative_step,
            warmup_init=warmup_init,
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                if grad.is_sparse:
                    raise RuntimeError("AdaFactor does not support sparse gradients")

                state = self.state[p]
                if len(state) == 0:
                    state["step"] = 0

                # Get factored moments for 2D parameters
                if grad.dim() == 2:
                    if "row_var" not in state:
                        state["row_var"] = torch.zeros(grad.size(0), **{"device": grad.device, "dtype": grad.dtype})
                        state["col_var"] = torch.zeros(grad.size(1), **{"device": grad.device, "dtype": grad.dtype})
                    row_var = state["row_var"]
                    col_var = state["col_var"]
                    factored = True
                else:
                    if "v" not in state:
                        state["v"] = torch.zeros_like(grad)
                    v = state["v"]
                    factored = False

                if "m" not in state:
                    state["m"] = torch.zeros_like(grad)
                m = state["m"]

                beta1 = group["beta1"]
                beta2 = group["beta2"]
                step = state["step"] + 1
                state["step"] = step

                # Non-adaptive scaling factor
                if group["relative_step"]:
                    lr = max(group["lr"], 1e-4 / step**0.5)
                else:
                    lr = group["lr"]

                # Update first moment
                m.mul_(beta1).add_(grad, alpha=1 - beta1)

                # Update second moment (factored or not)
                grad_squared = grad * grad
                if factored:
                    row_var.mul_(beta2).add_(grad_squared.mean(dim=1), alpha=1 - beta2)
                    col_var.mul_(beta2).add_(grad_squared.mean(dim=0), alpha=1 - beta2)
                    rust = row_var.unsqueeze(1) / row_var.mean().clamp(min=group["eps2"])
                    cust = col_var.unsqueeze(0) / col_var.mean().clamp(min=group["eps2"])
                    u = rust * cust
                    denom = u.clamp_(min=group["eps2"])
                else:
                    v.mul_(beta2).add_(grad_squared, alpha=1 - beta2)
                    denom = v.sqrt().add_(group["eps2"])

                # Gradient clipping
                rms = grad_squared.mean().sqrt().clamp(min=group["eps2"])
                clip_ratio = group["clip_threshold"] / rms
                clipped_grad = grad * min(clip_ratio, 1.0)

                # Update
                update = clipped_grad / denom.sqrt().clamp(min=group["eps1"])

                # Parameter scaling
                if group["scale_parameter"]:
                    param_scale = p.data.norm().clamp(min=group["eps2"])
                    update *= param_scale

                # Apply weight decay
                if group["weight_decay"] > 0:
                    p.data.mul_(1 - lr * group["weight_decay"])

                # Apply update
                p.data.add_(update, alpha=-lr)

        return loss


class NovoGrad(Optimizer):
    """NovoGrad optimizer.

    As described in https://arxiv.org/abs/1905.11286.

    Uses layer-wise gradient normalization.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-3.
        betas: Coefficients for running averages. Default: (0.95, 0.98).
        eps: Term for numerical stability. Default: 1e-8.
        weight_decay: Weight decay coefficient. Default: 0.0.
        grad_averaging: Whether to use gradient averaging. Default: False.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        betas: Tuple[float, float] = (0.95, 0.98),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
        grad_averaging: bool = False,
    ) -> None:
        """Initialize NovoGrad optimizer.

        Args:
            params: Model parameters.
            lr: Learning rate.
            betas: Momentum coefficients.
            eps: Numerical stability.
            weight_decay: Weight decay.
            grad_averaging: Use gradient averaging.
        """
        defaults = dict(
            lr=lr,
            betas=betas,
            eps=eps,
            weight_decay=weight_decay,
            grad_averaging=grad_averaging,
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            lr = group["lr"]
            eps = group["eps"]
            weight_decay = group["weight_decay"]
            grad_averaging = group["grad_averaging"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]

                if len(state) == 0:
                    state["step"] = 0
                    state["v"] = torch.zeros_like(p.data)
                    state["grad_norm_avg"] = torch.zeros(1, device=p.device, dtype=p.dtype)

                v = state["v"]
                grad_norm_avg = state["grad_norm_avg"]
                step = state["step"] + 1
                state["step"] = step

                # Gradient norm
                grad_norm = grad.norm().pow(2)

                # Update gradient norm average
                grad_norm_avg.mul_(beta2).add_(grad_norm, alpha=1 - beta2)

                # Normalize gradient
                grad_normalized = grad / (grad_norm_avg.sqrt() + eps)

                # Update momentum
                v.mul_(beta1).add_(grad_normalized, alpha=1 - beta1)

                # Bias correction
                bias_correction = 1 - beta1**step
                v_hat = v / bias_correction

                # Apply weight decay
                if weight_decay > 0:
                    p.data.mul_(1 - lr * weight_decay)

                # Apply update
                if grad_averaging:
                    v_hat = v_hat / (1 - beta1**step)

                p.data.add_(v_hat, alpha=-lr)

        return loss


class Ranger(Optimizer):
    """Ranger optimizer - RAdam + LookAhead.

    Combines RAdam (Rectified Adam) with LookAhead.

    Args:
        params: Model parameters or parameter groups.
        lr: Learning rate. Default: 1e-3.
        betas: Coefficients for running averages. Default: (0.9, 0.999).
        eps: Term for numerical stability. Default: 1e-8.
        weight_decay: Weight decay coefficient. Default: 0.0.
        k: LookAhead rate. Default: 6.
        alpha: LookAhead slow step size. Default: 0.5.
    """

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        betas: Tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
        k: int = 6,
        alpha: float = 0.5,
    ) -> None:
        """Initialize Ranger optimizer.

        Args:
            params: Model parameters.
            lr: Learning rate.
            betas: Momentum coefficients.
            eps: Numerical stability.
            weight_decay: Weight decay.
            k: LookAhead sync period.
            alpha: LookAhead slow step interpolation factor.
        """
        defaults = dict(
            lr=lr,
            betas=betas,
            eps=eps,
            weight_decay=weight_decay,
            k=k,
            alpha=alpha,
        )
        super().__init__(params, defaults)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None) -> Optional[float]:
        """Perform a single optimization step.

        Args:
            closure: A closure that reevaluates the model and returns the loss.

        Returns:
            The loss value, if closure is provided.
        """
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            lr = group["lr"]
            eps = group["eps"]
            weight_decay = group["weight_decay"]
            k = group["k"]
            alpha = group["alpha"]

            for p in group["params"]:
                if p.grad is None:
                    continue

                grad = p.grad.data
                state = self.state[p]

                if len(state) == 0:
                    state["step"] = 0
                    state["exp_avg"] = torch.zeros_like(p.data)
                    state["exp_avg_sq"] = torch.zeros_like(p.data)
                    state["slow_buffer"] = p.data.clone()

                exp_avg, exp_avg_sq = state["exp_avg"], state["exp_avg_sq"]
                slow_buffer = state["slow_buffer"]
                step = state["step"] + 1
                state["step"] = step

                # Compute gradient norm
                buffered = min(step, 10.0)
                numel = p.numel()

                # Update biased first moment estimate
                exp_avg.mul_(beta1).add_(grad, alpha=1 - beta1)
                # Update biased second raw moment estimate
                exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1 - beta2)

                # Compute bias-corrected moment estimates
                bias_correction1 = 1 - beta1**step
                bias_correction2 = 1 - beta2**step

                # RAdam correction
                rho_inf = 2 / (1 - beta2) - 1
                rho = (
                    rho_inf
                    - 2 * step * beta2 ** (step / 2) / (1 - beta2**step)
                )

                if rho > 5:
                    r = ((rho - 4) * (rho - 2) * rho_inf) / (
                        (rho_inf - 4) * (rho_inf - 2) * rho
                    )
                    num = exp_avg / bias_correction1
                    denom = (exp_avg_sq / bias_correction2).sqrt().add_(eps)
                    update = num / denom * r
                else:
                    update = exp_avg / bias_correction1

                # Apply weight decay
                if weight_decay > 0:
                    p.data.mul_(1 - lr * weight_decay)

                # Apply update
                p.data.add_(update, alpha=-lr)

                # LookAhead
                if step % k == 0:
                    slow_buffer.data.add_(p.data - slow_buffer, alpha=alpha)
                    p.data.copy_(slow_buffer)

        return loss


def build_optimizer(
    model: nn.Module,
    optimizer_name: str = "adamw",
    lr: float = 1e-4,
    weight_decay: float = 0.01,
    betas: Tuple[float, float] = (0.9, 0.999),
    eps: float = 1e-8,
    momentum: float = 0.9,
    no_decay_params: Optional[List[str]] = None,
    parameter_groups: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Optimizer:
    """Build an optimizer for a model.

    Args:
        model: The model to optimize.
        optimizer_name: Name of the optimizer ('adam', 'adamw', 'sgd', 'lion',
            'adamw_8bit', 'adafactor', 'lamb', 'novograd', 'ranger', 'sophia').
        lr: Learning rate.
        weight_decay: Weight decay coefficient.
        betas: Coefficients for running averages (for adaptive optimizers).
        eps: Term for numerical stability.
        momentum: Momentum factor (for SGD).
        no_decay_params: Layer name substrings that should not have weight decay.
        parameter_groups: Pre-defined parameter groups.
        **kwargs: Additional optimizer-specific arguments.

    Returns:
        The configured optimizer.

    Raises:
        ValueError: If the optimizer name is not recognized.
    """
    if parameter_groups is not None:
        params = parameter_groups
    else:
        from .model import get_parameter_groups
        params = get_parameter_groups(model, weight_decay, no_decay_params)

    optimizer_name = optimizer_name.lower().replace("-", "_")

    if optimizer_name == "adam":
        return torch.optim.Adam(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "adamw":
        return torch.optim.AdamW(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "sgd":
        return torch.optim.SGD(params, lr=lr, momentum=momentum, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "lion":
        return Lion(params, lr=lr, betas=(betas[0], betas[1]), weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "adamw_8bit":
        try:
            import bitsandbytes as bnb
            return bnb.optim.AdamW8bit(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)
        except ImportError:
            logger.warning("bitsandbytes not available, falling back to AdamW")
            return torch.optim.AdamW(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "adafactor":
        return AdaFactor(params, lr=lr, beta1=betas[0], beta2=betas[1], weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "lamb":
        return LAMB(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "novograd":
        return NovoGrad(params, lr=lr, betas=(betas[0], betas[1]), eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "ranger":
        return Ranger(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, **kwargs)

    elif optimizer_name == "sophia":
        return SophiaG(params, lr=lr, betas=(betas[0], betas[1]), weight_decay=weight_decay, **kwargs)

    else:
        raise ValueError(
            f"Unknown optimizer: '{optimizer_name}'. "
            f"Available: adam, adamw, sgd, lion, adamw_8bit, adafactor, "
            f"lamb, novograd, ranger, sophia"
        )


def get_optimizer_info(optimizer: Optimizer) -> Dict[str, Any]:
    """Get information about an optimizer.

    Args:
        optimizer: The optimizer instance.

    Returns:
        Dictionary with optimizer metadata.
    """
    info: Dict[str, Any] = {
        "type": type(optimizer).__name__,
        "param_groups": len(optimizer.param_groups),
        "total_params": sum(
            sum(p.numel() for p in group["params"])
            for group in optimizer.param_groups
        ),
    }

    for i, group in enumerate(optimizer.param_groups):
        group_info = {k: v for k, v in group.items() if k != "params"}
        info[f"group_{i}"] = group_info

    return info


def zero_grad_all(optimizer: Optimizer, set_to_none: bool = True) -> None:
    """Zero gradients for all parameter groups.

    Args:
        optimizer: The optimizer.
        set_to_none: Set grads to None instead of zero (more memory efficient).
    """
    for group in optimizer.param_groups:
        for p in group["params"]:
            if p.grad is not None:
                if set_to_none:
                    p.grad = None
                else:
                    p.grad.zero_()
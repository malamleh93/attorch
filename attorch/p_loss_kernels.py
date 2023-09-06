"""
Kernels for p-norm-induced losses.
"""


import triton
import triton.language as tl


@triton.autotune(
    configs=[
        triton.Config({'BLOCK_SIZE': 64}, num_warps=2),
        triton.Config({'BLOCK_SIZE': 128}, num_warps=2),
        triton.Config({'BLOCK_SIZE': 256}, num_warps=4),
        triton.Config({'BLOCK_SIZE': 512}, num_warps=4),
        triton.Config({'BLOCK_SIZE': 1024}, num_warps=4),
    ],
    key=['size'],
    reset_to_zero=['output_pointer'],
)
@triton.jit
def p_loss_forward_kernel(
    input_pointer, target_pointer, output_pointer,
    size, p_loss: tl.constexpr, reduction: tl.constexpr,
    BLOCK_SIZE: tl.constexpr,
    ):
    """
    Measures the L1 or squared L2 norm of the difference between the input
    and target (i.e., mean absolute error or mean squared error).

    Args:
        input_pointer: Pointer to the input.
            The input must be of shape [size].
        target_pointer: Pointer to the target.
            The target must be of shape [size].
        output_pointer: Pointer to a container the error is written to.
            The container must be of shape [size] if reduction is 'none',
            and otherwise a scalar.
        size: Number of elements in the input and target.
        p_loss: p-norm used to compute the error.
            Options are 1 for MAE and 2 for MSE.
        reduction: Reduction strategy for the output.
            Options are 'none' for no reduction, 'mean' for averaging the error
            across all entries, and 'sum' for summing the error across all entries.
        BLOCK_SIZE: Block size.
    """
    # This program processes BLOCK_SIZE rows.
    pid = tl.program_id(axis=0)
    offset = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offset < size

    input = tl.load(input_pointer + offset, mask=mask)
    target = tl.load(target_pointer + offset, mask=mask)
    diff = input - target

    if p_loss == 1:
        error = tl.abs(diff)

    elif p_loss == 2:
        error = diff * diff

    if reduction == 'none':
        tl.store(output_pointer + offset, error, mask=mask)

    elif reduction == 'mean':
        tl.atomic_add(output_pointer, tl.sum(error) / size)

    elif reduction == 'sum':
        tl.atomic_add(output_pointer, tl.sum(error))


@triton.autotune(
    configs=[
        triton.Config({'BLOCK_SIZE': 64}, num_warps=2),
        triton.Config({'BLOCK_SIZE': 128}, num_warps=2),
        triton.Config({'BLOCK_SIZE': 256}, num_warps=4),
        triton.Config({'BLOCK_SIZE': 512}, num_warps=4),
        triton.Config({'BLOCK_SIZE': 1024}, num_warps=4),
    ],
    key=['size'],
)
@triton.jit
def p_loss_backward_kernel(
    output_grad_pointer, input_pointer, target_pointer,
    input_grad_pointer, target_grad_pointer, size,
    p_loss: tl.constexpr, reduction: tl.constexpr,
    BLOCK_SIZE: tl.constexpr,
    ):
    """
    Calculates the input gradient of the mean absolute error or
    mean squared error.

    Args:
        output_grad_pointer: Pointer to the error's output gradients.
            The output container must be a scalar or of shape [size].
        input_pointer: Pointer to the input.
            The input must be of shape [size].
        target_pointer: Pointer to the target.
            The target must be of shape [size].
        input_grad_pointer: Pointer to a container the input's gradients are written to.
            The container must be of shape [size].
        target_grad_pointer: Pointer to a container the target's gradients are written to.
            The container must be of shape [size].
        size: Number of elements in the input and target.
        p_loss: p-norm used to compute the error whose gradient is calculated.
            Options are 1 for MAE and 2 for MSE.
        reduction: Reduction strategy for the output whose gradient is calculated.
            Options are 'none' for no reduction, 'mean' for averaging the error
            across all entries, and 'sum' for summing the error across all entries.
        BLOCK_SIZE: Block size.
    """
    # This program processes BLOCK_SIZE rows.
    pid = tl.program_id(axis=0)
    offset = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offset < size

    output_grad_mask = None
    if reduction == 'none':
        output_grad_pointer += offset
        output_grad_mask = mask

    input = tl.load(input_pointer + offset, mask=mask)
    target = tl.load(target_pointer + offset, mask=mask)
    output_grad = tl.load(output_grad_pointer, mask=output_grad_mask)

    if p_loss == 1:
        input_grad = tl.where(target <= input, 1, -1)

    elif p_loss == 2:
        input_grad = 2 * (input - target)

    if reduction == 'mean':
        input_grad /= size

    input_grad *= output_grad
    tl.store(input_grad_pointer + offset, input_grad, mask=mask)
    tl.store(target_grad_pointer + offset, -input_grad, mask=mask)

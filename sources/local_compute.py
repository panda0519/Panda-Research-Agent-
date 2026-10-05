"""Local deterministic offline computation checker for arithmetic, unit conversions, and asymptotic complexity."""
from __future__ import annotations

import ast
import logging
import math
import operator
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Safe operator mapping for AST evaluator
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Unit conversion tables normalized to base units
_DATA_SIZE_TO_BYTES: Dict[str, float] = {
    "bit": 0.125,
    "bits": 0.125,
    "byte": 1.0,
    "bytes": 1.0,
    "b": 1.0,
    "kb": 1024.0,
    "kib": 1024.0,
    "mb": 1024.0**2,
    "mib": 1024.0**2,
    "gb": 1024.0**3,
    "gib": 1024.0**3,
    "tb": 1024.0**4,
    "tib": 1024.0**4,
    "pb": 1024.0**5,
}

_TIME_TO_SECONDS: Dict[str, float] = {
    "ns": 1e-9,
    "nanosecond": 1e-9,
    "nanoseconds": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "microsecond": 1e-6,
    "microseconds": 1e-6,
    "ms": 1e-3,
    "millisecond": 1e-3,
    "milliseconds": 1e-3,
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}

_FREQUENCY_TO_HZ: Dict[str, float] = {
    "hz": 1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
    "thz": 1e12,
}

# Asymptotic complexity ordering (lower index = strictly faster / lower growth)
_COMPLEXITY_RANKS = [
    (re.compile(r"o\(1\)", re.I), 0, "O(1)"),
    (re.compile(r"o\(log\s*log\s*n\)", re.I), 1, "O(log log n)"),
    (re.compile(r"o\((?:log|ln)\s*n\)", re.I), 2, "O(log n)"),
    (re.compile(r"o\((?:log\s*n)\^[0-9]+\)", re.I), 3, "O(polylog n)"),
    (re.compile(r"o\((?:sqrt|√)\s*\(?n\)?\)", re.I), 4, "O(sqrt n)"),
    (re.compile(r"o\(n\)", re.I), 5, "O(n)"),
    (re.compile(r"o\(n\s*(?:log|ln)\s*n\)", re.I), 6, "O(n log n)"),
    (re.compile(r"o\(n\^2\)", re.I), 7, "O(n^2)"),
    (re.compile(r"o\(n\^3\)", re.I), 8, "O(n^3)"),
    (re.compile(r"o\(n\^[4-9]\)", re.I), 9, "O(n^k)"),
    (re.compile(r"o\(2\^n\)", re.I), 10, "O(2^n)"),
    (re.compile(r"o\([3-9]\^n\)", re.I), 11, "O(k^n)"),
    (re.compile(r"o\(n!\)", re.I), 12, "O(n!)"),
    (re.compile(r"o\(n\^n\)", re.I), 13, "O(n^n)"),
]


@dataclass
class ComputationResult:
    claim_type: str  # "arithmetic", "unit_conversion", "complexity", "percentage"
    expression: str
    computed_value: Any
    claimed_value: Optional[Any] = None
    is_verified: bool = False
    discrepancy_note: Optional[str] = None


def _eval_ast_node(node: ast.AST) -> Union[int, float]:
    """Recursively evaluates an AST node safely without calling eval()."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type in _SAFE_OPERATORS:
            operand = _eval_ast_node(node.operand)
            return _SAFE_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type}")
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type in _SAFE_OPERATORS:
            left = _eval_ast_node(node.left)
            right = _eval_ast_node(node.right)
            # Guard against giant exponentiation
            if op_type == ast.Pow:
                if abs(right) > 100 or (abs(left) > 1e4 and right > 10):
                    raise ValueError(f"Exponentiation too large: {left} ** {right}")
            # Guard against division by zero
            if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
                raise ZeroDivisionError("Division by zero in arithmetic expression")
            return _SAFE_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type}")
    raise ValueError(f"Unsupported AST node: {type(node)}")


def evaluate_arithmetic(expr: str) -> Optional[Union[int, float]]:
    """Safely evaluates a pure arithmetic expression string.

    Returns the numeric result or None if expression is invalid or unsafe.
    """
    clean = expr.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    # Remove surrounding equals if present
    clean = re.sub(r"=.*$", "", clean).strip()

    try:
        parsed = ast.parse(clean, mode="eval")
        result = _eval_ast_node(parsed)
        if isinstance(result, (int, float)) and not math.isnan(result) and not math.isinf(result):
            return result
        return None
    except Exception as exc:
        logger.debug("Safe arithmetic evaluation failed for '%s': %s", expr, exc)
        return None


def evaluate_unit_conversion(val: float, from_unit: str, to_unit: str) -> Optional[float]:
    """Converts a value between compatible units (data size, time, frequency)."""
    f_u = from_unit.strip().lower()
    t_u = to_unit.strip().lower()

    if f_u == t_u:
        return val

    # Data size
    if f_u in _DATA_SIZE_TO_BYTES and t_u in _DATA_SIZE_TO_BYTES:
        bytes_val = val * _DATA_SIZE_TO_BYTES[f_u]
        return bytes_val / _DATA_SIZE_TO_BYTES[t_u]

    # Time
    if f_u in _TIME_TO_SECONDS and t_u in _TIME_TO_SECONDS:
        seconds_val = val * _TIME_TO_SECONDS[f_u]
        return seconds_val / _TIME_TO_SECONDS[t_u]

    # Frequency
    if f_u in _FREQUENCY_TO_HZ and t_u in _FREQUENCY_TO_HZ:
        hz_val = val * _FREQUENCY_TO_HZ[f_u]
        return hz_val / _FREQUENCY_TO_HZ[t_u]

    return None


def parse_complexity_rank(text: str) -> Optional[Tuple[int, str]]:
    """Returns (rank_index, canonical_label) for asymptotic complexity notation."""
    clean = text.strip().replace(" ", "")
    for pattern, rank, label in _COMPLEXITY_RANKS:
        if pattern.search(clean):
            return rank, label
    return None


def compare_complexity(c1: str, c2: str) -> Optional[int]:
    """Compares two complexity strings.

    Returns:
      -1 if c1 < c2 (c1 has strictly lower asymptotic complexity / faster)
       0 if c1 == c2 (same asymptotic complexity class)
       1 if c1 > c2 (c1 has higher asymptotic complexity / slower)
       None if either expression cannot be parsed
    """
    res1 = parse_complexity_rank(c1)
    res2 = parse_complexity_rank(c2)
    if res1 is None or res2 is None:
        return None
    r1, _ = res1
    r2, _ = res2
    if r1 < r2:
        return -1
    elif r1 > r2:
        return 1
    return 0


def verify_computational_claim(claim_text: str) -> Optional[ComputationResult]:
    """Parses and checks quantitative, conversion, or complexity claims in natural language."""
    clean = claim_text.strip()

    # 1. Check complexity comparison claims (e.g. "reduces complexity from O(n^2) to O(n log n)")
    comp_match = re.search(r"from\s+(O\([^)]+\))\s+to\s+(O\([^)]+\))", clean, re.IGNORECASE)
    if comp_match:
        from_comp, to_comp = comp_match.group(1), comp_match.group(2)
        cmp_res = compare_complexity(from_comp, to_comp)
        if cmp_res is not None:
            improved = cmp_res > 0  # from > to means improvement
            return ComputationResult(
                claim_type="complexity",
                expression=f"{from_comp} -> {to_comp}",
                computed_value=f"Reduction: {improved}",
                claimed_value="Reduction",
                is_verified=improved,
                discrepancy_note=None if improved else f"{to_comp} is not lower complexity than {from_comp}",
            )

    # 2. Check percentage reduction/increase claims (e.g., "reduces latency from 200ms to 50ms (a 75% reduction)")
    pct_match = re.search(
        r"from\s+([0-9.]+)\s*([a-zA-Zµ]+)?\s+to\s+([0-9.]+)\s*([a-zA-Zµ]+)?.*?([0-9.]+)%\s*(reduction|decrease|drop|improvement|increase|growth)?",
        clean,
        re.IGNORECASE,
    )
    if pct_match:
        try:
            v1 = float(pct_match.group(1))
            u1 = pct_match.group(2) or ""
            v2 = float(pct_match.group(3))
            u2 = pct_match.group(4) or u1
            claimed_pct = float(pct_match.group(5))
            direction = (pct_match.group(6) or "").lower()

            # Normalize units if different
            if u1 and u2 and u1.lower() != u2.lower():
                conv_v2 = evaluate_unit_conversion(v2, u2, u1)
                if conv_v2 is not None:
                    v2 = conv_v2

            if v1 != 0:
                actual_pct = abs((v1 - v2) / v1) * 100.0
                is_reduction = v2 < v1
                is_dir_ok = True
                if direction in ("reduction", "decrease", "drop") and not is_reduction:
                    is_dir_ok = False
                elif direction in ("increase", "growth") and is_reduction:
                    is_dir_ok = False

                diff = abs(actual_pct - claimed_pct)
                is_ok = is_dir_ok and (diff <= 1.5 or (claimed_pct != 0 and diff / claimed_pct <= 0.05))

                return ComputationResult(
                    claim_type="percentage",
                    expression=f"|{v1} - {v2}| / {v1} * 100",
                    computed_value=round(actual_pct, 2),
                    claimed_value=claimed_pct,
                    is_verified=is_ok,
                    discrepancy_note=None if is_ok else f"Computed {actual_pct:.1f}%, claimed {claimed_pct:.1f}%",
                )
        except Exception:
            pass

    # 3. Check explicit arithmetic equality (e.g., "1024 * 768 = 786432" or "500 / 10 = 50")
    eq_match = re.search(r"([0-9\s.+\-*/^()×÷]+)\s*=\s*([0-9.]+)", clean)
    if eq_match:
        expr_str = eq_match.group(1).strip()
        claimed_num_str = eq_match.group(2).strip()
        calc = evaluate_arithmetic(expr_str)
        if calc is not None:
            try:
                claimed_val = float(claimed_num_str)
                diff = abs(calc - claimed_val)
                is_match = diff < 1e-4 or (claimed_val != 0 and diff / abs(claimed_val) < 0.01)
                return ComputationResult(
                    claim_type="arithmetic",
                    expression=expr_str,
                    computed_value=calc,
                    claimed_value=claimed_val,
                    is_verified=is_match,
                    discrepancy_note=None if is_match else f"Computed {calc}, claimed {claimed_val}",
                )
            except ValueError:
                pass

    return None

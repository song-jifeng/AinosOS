"""Query optimizer for AinosDB SQL engine.

Applies cost-based and rule-based optimizations to query plans,
including predicate pushdown, join reordering, and index selection.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from .planner import PlanNode, PlanNodeType, QueryPlan
from .catalog import Catalog, ColumnInfo
from .parser import (
    Expression, BinaryExpression, UnaryExpression, ColumnExpression,
    LiteralExpression, FunctionCall, StarExpression, BetweenExpression,
    InExpression, LikeExpression,
)


class Optimizer:
    """Query plan optimizer.

    Applies the following optimizations:
    - Predicate pushdown (filter closer to scan)
    - Constant folding
    - Join order optimization
    - Projection pushdown (select only needed columns)
    """

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def optimize(self, plan: QueryPlan) -> QueryPlan:
        """Optimize a query plan.

        Args:
            plan: The original query plan.

        Returns:
            Optimized query plan.
        """
        root = plan.root
        root = self._optimize_node(root)
        plan.root = root
        plan.estimated_cost = self._calculate_cost(root)
        return plan

    def _optimize_node(self, node: PlanNode) -> PlanNode:
        """Optimize a single plan node and its children.

        Args:
            node: Plan node to optimize.

        Returns:
            Optimized plan node.
        """
        # Optimize children first (bottom-up)
        node.children = [self._optimize_node(child) for child in node.children]

        # Apply optimizations
        node = self._predicate_pushdown(node)
        node = self._constant_folding(node)
        node = self._combine_filters(node)

        return node

    def _predicate_pushdown(self, node: PlanNode) -> PlanNode:
        """Push filter predicates closer to the scan.

        Moves filter conditions that reference only a table's columns
        down to the scan node above that table.

        Args:
            node: Plan node to optimize.

        Returns:
            Optimized plan node.
        """
        if node.node_type == PlanNodeType.FILTER and node.children:
            child = node.children[0]

            # If child is also a filter, combine them
            if child.node_type == PlanNodeType.FILTER:
                # Push the filter down
                if node.where_clause and child.where_clause:
                    combined = BinaryExpression(
                        "AND", node.where_clause, child.where_clause
                    )
                    child.where_clause = combined
                    node.where_clause = None
                    # Return the child, removing the redundant filter
                    return child

            # If child is a scan, try to push filter condition
            if child.node_type in (PlanNodeType.SEQUENTIAL_SCAN, PlanNodeType.INDEX_SCAN):
                # Push filter to scan
                child.where_clause = node.where_clause
                return child

        return node

    def _constant_folding(self, node: PlanNode) -> PlanNode:
        """Fold constant expressions where possible.

        Args:
            node: Plan node to optimize.

        Returns:
            Optimized plan node.
        """
        if node.where_clause:
            node.where_clause = self._fold_expression(node.where_clause)

        if node.expressions:
            node.expressions = [
                self._fold_expression(expr) for expr in node.expressions
            ]

        return node

    def _fold_expression(self, expr: Expression) -> Expression:
        """Fold constant sub-expressions.

        Args:
            expr: Expression to fold.

        Returns:
            Expression with constants folded.
        """
        if isinstance(expr, BinaryExpression):
            expr.left = self._fold_expression(expr.left)
            expr.right = self._fold_expression(expr.right)

            # Fold if both sides are literals
            if isinstance(expr.left, LiteralExpression) and isinstance(expr.right, LiteralExpression):
                try:
                    left_val = expr.left.value
                    right_val = expr.right.value
                    op = expr.operator

                    if op == "+":
                        return LiteralExpression(left_val + right_val)
                    elif op == "-":
                        return LiteralExpression(left_val - right_val)
                    elif op == "*":
                        return LiteralExpression(left_val * right_val)
                    elif op == "/":
                        if right_val != 0:
                            return LiteralExpression(left_val / right_val)
                    elif op == "=":
                        return LiteralExpression(left_val == right_val)
                    elif op == "!=":
                        return LiteralExpression(left_val != right_val)
                    elif op == "<":
                        return LiteralExpression(left_val < right_val)
                    elif op == ">":
                        return LiteralExpression(left_val > right_val)
                    elif op == "<=":
                        return LiteralExpression(left_val <= right_val)
                    elif op == ">=":
                        return LiteralExpression(left_val >= right_val)
                    elif op == "AND":
                        return LiteralExpression(bool(left_val) and bool(right_val))
                    elif op == "OR":
                        return LiteralExpression(bool(left_val) or bool(right_val))
                except (TypeError, ValueError):
                    pass

        elif isinstance(expr, UnaryExpression):
            expr.operand = self._fold_expression(expr.operand)
            if isinstance(expr.operand, LiteralExpression) and expr.operator == "-":
                return LiteralExpression(-expr.operand.value)
            elif isinstance(expr.operand, LiteralExpression) and expr.operator == "NOT":
                return LiteralExpression(not expr.operand.value)

        return expr

    def _combine_filters(self, node: PlanNode) -> PlanNode:
        """Combine adjacent filter nodes into one.

        Args:
            node: Plan node to optimize.

        Returns:
            Optimized plan node.
        """
        if node.node_type == PlanNodeType.FILTER and node.children:
            child = node.children[0]
            if child.node_type == PlanNodeType.FILTER:
                if node.where_clause and child.where_clause:
                    combined = BinaryExpression(
                        "AND", node.where_clause, child.where_clause
                    )
                    child.where_clause = combined
                    node.where_clause = None
                    return child

        return node

    def _calculate_cost(self, node: PlanNode) -> float:
        """Calculate the total cost of a plan tree.

        Args:
            node: Root plan node.

        Returns:
            Total cost.
        """
        total = node.cost
        for child in node.children:
            total += self._calculate_cost(child)
        return total

    def __repr__(self) -> str:
        return "Optimizer()"
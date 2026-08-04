"""Query planner for AinosDB SQL engine.

Transforms parsed AST into executable query plans consisting
of plan nodes (scan, filter, project, join, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Union
from .parser import (
    Statement, SelectStatement, InsertStatement, CreateStatement,
    DeleteStatement, UpdateStatement, DropStatement, AlterStatement,
    UseStatement, ShowStatement, TransactionStatement, ExplainStatement,
    Expression, LiteralExpression, ColumnExpression, BinaryExpression,
    UnaryExpression, FunctionCall, StarExpression, JoinClause, OrderByItem,
    BetweenExpression, InExpression, LikeExpression, CaseExpression,
    SubqueryExpression, ColumnDef,
)
from .catalog import Catalog, TableInfo, ColumnInfo
from .types import DataType, parse_type_string


class PlanNodeType(Enum):
    """Types of plan nodes."""
    SEQUENTIAL_SCAN = auto()
    INDEX_SCAN = auto()
    FILTER = auto()
    PROJECTION = auto()
    INSERT = auto()
    CREATE_TABLE = auto()
    CREATE_DATABASE = auto()
    DROP_TABLE = auto()
    DROP_DATABASE = auto()
    DELETE = auto()
    UPDATE = auto()
    NESTED_LOOP_JOIN = auto()
    HASH_JOIN = auto()
    SORT = auto()
    LIMIT = auto()
    AGGREGATE = auto()
    DISTINCT = auto()
    EXPLAIN = auto()
    USE_DATABASE = auto()
    SHOW = auto()
    TRANSACTION = auto()
    ALTER_TABLE = auto()
    VECTOR_INDEX_SCAN = auto()
    DOCUMENT_SCAN = auto()


@dataclass
class PlanNode:
    """A node in the query execution plan.

    Attributes:
        node_type: Type of plan node.
        children: Child plan nodes.
        cost: Estimated execution cost.
        cardinality: Estimated number of output rows.
        output_schema: List of (column_name, data_type) tuples.
    """

    node_type: PlanNodeType
    children: List["PlanNode"] = field(default_factory=list)
    cost: float = 0.0
    cardinality: int = 0
    output_schema: List[Tuple[str, DataType]] = field(default_factory=list)

    # Node-specific attributes
    table_name: Optional[str] = None
    table_alias: Optional[str] = None
    database_name: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    expressions: List[Expression] = field(default_factory=list)
    where_clause: Optional[Expression] = None
    set_clauses: List[Tuple[str, Expression]] = field(default_factory=list)
    values: List[List[Expression]] = field(default_factory=list)
    column_defs: List[ColumnDef] = field(default_factory=list)
    join_type: Optional[str] = None
    join_condition: Optional[Expression] = None
    order_by: List[OrderByItem] = field(default_factory=list)
    limit_count: Optional[int] = None
    offset_count: Optional[int] = None
    group_by: List[Expression] = field(default_factory=list)
    having: Optional[Expression] = None
    is_distinct: bool = False
    object_type: Optional[str] = None
    action: Optional[str] = None
    column_name: Optional[str] = None
    if_not_exists: bool = False
    if_exists: bool = False
    statement: Optional[Statement] = None

    def __repr__(self) -> str:
        return f"PlanNode({self.node_type.name}, cost={self.cost:.2f}, rows={self.cardinality})"


@dataclass
class QueryPlan:
    """Complete query execution plan.

    Attributes:
        root: Root plan node.
        statement: Original SQL statement.
        estimated_cost: Total estimated execution cost.
    """

    root: PlanNode
    statement: Statement
    estimated_cost: float = 0.0

    def __repr__(self) -> str:
        return f"QueryPlan(cost={self.estimated_cost:.2f})\n{self._format_node(self.root, 0)}"

    def _format_node(self, node: PlanNode, depth: int) -> str:
        indent = "  " * depth
        lines = [f"{indent}{node.node_type.name} (cost={node.cost:.2f}, rows={node.cardinality})"]
        if node.table_name:
            lines.append(f"{indent}  table: {node.table_name}")
        if node.where_clause:
            lines.append(f"{indent}  filter: {node.where_clause}")
        for child in node.children:
            lines.append(self._format_node(child, depth + 1))
        return "\n".join(lines)


class Planner:
    """Query planner that transforms AST into execution plans.

    Uses the catalog to resolve table and column references, and
    generates plan nodes for each operation.

    Attributes:
        catalog: System catalog for schema resolution.
    """

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def create_plan(self, statement: Statement) -> QueryPlan:
        """Create an execution plan for a SQL statement.

        Args:
            statement: Parsed AST statement.

        Returns:
            QueryPlan with execution plan tree.

        Raises:
            ValueError: If the statement cannot be planned.
        """
        if isinstance(statement, SelectStatement):
            return self._plan_select(statement)
        elif isinstance(statement, InsertStatement):
            return self._plan_insert(statement)
        elif isinstance(statement, CreateStatement):
            return self._plan_create(statement)
        elif isinstance(statement, DeleteStatement):
            return self._plan_delete(statement)
        elif isinstance(statement, UpdateStatement):
            return self._plan_update(statement)
        elif isinstance(statement, DropStatement):
            return self._plan_drop(statement)
        elif isinstance(statement, AlterStatement):
            return self._plan_alter(statement)
        elif isinstance(statement, UseStatement):
            return self._plan_use(statement)
        elif isinstance(statement, ShowStatement):
            return self._plan_show(statement)
        elif isinstance(statement, TransactionStatement):
            return self._plan_transaction(statement)
        elif isinstance(statement, ExplainStatement):
            return self._plan_explain(statement)
        else:
            raise ValueError(f"Unsupported statement type: {type(statement).__name__}")

    def _plan_select(self, stmt: SelectStatement) -> QueryPlan:
        """Plan a SELECT statement.

        Builds a plan tree: Scan -> Filter -> Join -> Aggregate -> Sort -> Projection -> Limit
        """
        # Determine the output schema
        output_schema: List[Tuple[str, DataType]] = []
        table_info = None
        if stmt.from_table:
            try:
                table_info = self.catalog.get_table(stmt.from_table)
            except ValueError:
                pass

        # Build the base scan
        scan_node = PlanNode(
            node_type=PlanNodeType.SEQUENTIAL_SCAN,
            table_name=stmt.from_table,
            table_alias=stmt.from_alias,
            cost=10.0,
            cardinality=1000,
        )

        if table_info:
            scan_node.cardinality = max(table_info.row_count, 1)
            scan_node.cost = scan_node.cardinality * 0.01
            scan_node.output_schema = [
                (col.name, col.data_type) for col in table_info.columns
            ]

        current_node = scan_node

        # Apply WHERE filter
        if stmt.where_clause:
            filter_node = PlanNode(
                node_type=PlanNodeType.FILTER,
                children=[current_node],
                where_clause=stmt.where_clause,
                cost=current_node.cost * 1.1,
                cardinality=int(current_node.cardinality * 0.1),
                output_schema=current_node.output_schema,
            )
            current_node = filter_node

        # Handle JOINs
        for join in stmt.joins:
            join_node = PlanNode(
                node_type=PlanNodeType.NESTED_LOOP_JOIN,
                children=[current_node],
                table_name=join.table_name,
                join_type=join.join_type,
                join_condition=join.on_condition,
                cost=current_node.cost * 2.0,
                cardinality=int(current_node.cardinality * 0.5),
                output_schema=current_node.output_schema,
            )
            current_node = join_node

        # GROUP BY / Aggregate
        if stmt.group_by or self._has_aggregates(stmt.columns):
            agg_node = PlanNode(
                node_type=PlanNodeType.AGGREGATE,
                children=[current_node],
                expressions=stmt.columns,
                group_by=stmt.group_by,
                having=stmt.having,
                cost=current_node.cost * 1.5,
                cardinality=max(int(current_node.cardinality * 0.5), 1),
                output_schema=current_node.output_schema,
            )
            current_node = agg_node

        # ORDER BY
        if stmt.order_by:
            sort_node = PlanNode(
                node_type=PlanNodeType.SORT,
                children=[current_node],
                order_by=stmt.order_by,
                cost=current_node.cost * 2.0,
                cardinality=current_node.cardinality,
                output_schema=current_node.output_schema,
            )
            current_node = sort_node

        # DISTINCT
        if stmt.distinct:
            distinct_node = PlanNode(
                node_type=PlanNodeType.DISTINCT,
                children=[current_node],
                is_distinct=True,
                cost=current_node.cost * 1.2,
                cardinality=int(current_node.cardinality * 0.5),
                output_schema=current_node.output_schema,
            )
            current_node = distinct_node

        # Projection (SELECT columns)
        if stmt.columns:
            # Build the output schema for the projection
            proj_schema = self._resolve_projection_schema(stmt.columns, table_info)
            proj_node = PlanNode(
                node_type=PlanNodeType.PROJECTION,
                children=[current_node],
                expressions=stmt.columns,
                cost=current_node.cost * 1.05,
                cardinality=current_node.cardinality,
                output_schema=proj_schema,
            )
            current_node = proj_node

        # LIMIT / OFFSET
        if stmt.limit is not None or stmt.offset is not None:
            limit_node = PlanNode(
                node_type=PlanNodeType.LIMIT,
                children=[current_node],
                limit_count=stmt.limit,
                offset_count=stmt.offset,
                cost=current_node.cost,
                cardinality=min(current_node.cardinality, stmt.limit or current_node.cardinality),
                output_schema=current_node.output_schema,
            )
            current_node = limit_node

        # Calculate total cost
        total_cost = self._calculate_cost(current_node)

        return QueryPlan(root=current_node, statement=stmt, estimated_cost=total_cost)

    def _plan_insert(self, stmt: InsertStatement) -> QueryPlan:
        """Plan an INSERT statement."""
        node = PlanNode(
            node_type=PlanNodeType.INSERT,
            table_name=stmt.table_name,
            columns=stmt.columns,
            values=stmt.values,
            cost=1.0 + len(stmt.values) * 0.1,
            cardinality=len(stmt.values),
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_create(self, stmt: CreateStatement) -> QueryPlan:
        """Plan a CREATE statement."""
        node_type = (
            PlanNodeType.CREATE_TABLE
            if stmt.object_type == "TABLE"
            else PlanNodeType.CREATE_DATABASE
        )
        node = PlanNode(
            node_type=node_type,
            name=stmt.name,
            column_defs=stmt.columns,
            object_type=stmt.object_type,
            if_not_exists=stmt.if_not_exists,
            cost=1.0,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_delete(self, stmt: DeleteStatement) -> QueryPlan:
        """Plan a DELETE statement."""
        node = PlanNode(
            node_type=PlanNodeType.DELETE,
            table_name=stmt.table_name,
            where_clause=stmt.where_clause,
            cost=5.0,
            cardinality=100,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_update(self, stmt: UpdateStatement) -> QueryPlan:
        """Plan an UPDATE statement."""
        node = PlanNode(
            node_type=PlanNodeType.UPDATE,
            table_name=stmt.table_name,
            set_clauses=stmt.set_clauses,
            where_clause=stmt.where_clause,
            cost=5.0,
            cardinality=100,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_drop(self, stmt: DropStatement) -> QueryPlan:
        """Plan a DROP statement."""
        node_type = (
            PlanNodeType.DROP_TABLE
            if stmt.object_type == "TABLE"
            else PlanNodeType.DROP_DATABASE
        )
        node = PlanNode(
            node_type=node_type,
            name=stmt.name,
            object_type=stmt.object_type,
            if_exists=stmt.if_exists,
            cost=1.0,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_alter(self, stmt: AlterStatement) -> QueryPlan:
        """Plan an ALTER TABLE statement."""
        node = PlanNode(
            node_type=PlanNodeType.ALTER_TABLE,
            table_name=stmt.table_name,
            action=stmt.action,
            column_name=stmt.column_name if stmt.column_name else None,
            column_defs=[stmt.column] if stmt.column else [],
            cost=2.0,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_use(self, stmt: UseStatement) -> QueryPlan:
        """Plan a USE statement."""
        node = PlanNode(
            node_type=PlanNodeType.USE_DATABASE,
            database_name=stmt.database_name,
            cost=0.1,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_show(self, stmt: ShowStatement) -> QueryPlan:
        """Plan a SHOW statement."""
        node = PlanNode(
            node_type=PlanNodeType.SHOW,
            object_type=stmt.object_type,
            cost=0.1,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_transaction(self, stmt: TransactionStatement) -> QueryPlan:
        """Plan a transaction statement."""
        node = PlanNode(
            node_type=PlanNodeType.TRANSACTION,
            action=stmt.action,
            cost=0.1,
            cardinality=0,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _plan_explain(self, stmt: ExplainStatement) -> QueryPlan:
        """Plan an EXPLAIN statement."""
        inner_plan = self.create_plan(stmt.statement)
        node = PlanNode(
            node_type=PlanNodeType.EXPLAIN,
            children=[inner_plan.root],
            statement=stmt.statement,
            cost=0.1,
            cardinality=1,
        )
        return QueryPlan(root=node, statement=stmt, estimated_cost=node.cost)

    def _resolve_projection_schema(
        self,
        columns: List[Expression],
        table_info: Optional[TableInfo],
    ) -> List[Tuple[str, DataType]]:
        """Resolve the output schema for a projection.

        Args:
            columns: SELECT expressions.
            table_info: Optional table metadata.

        Returns:
            List of (column_name, data_type) tuples.
        """
        schema: List[Tuple[str, DataType]] = []

        for expr in columns:
            if isinstance(expr, StarExpression):
                # All columns
                if table_info:
                    for col in table_info.columns:
                        schema.append((col.name, col.data_type))
            elif isinstance(expr, ColumnExpression):
                if table_info:
                    col = table_info.get_column(expr.name)
                    if col:
                        schema.append((expr.name, col.data_type))
                    else:
                        schema.append((expr.name, parse_type_string("TEXT")))
                else:
                    schema.append((expr.name, parse_type_string("TEXT")))
            elif isinstance(expr, FunctionCall):
                # Aggregate functions return numeric types
                if expr.name in ("COUNT",):
                    from .types import IntegerType
                    schema.append((expr.name, IntegerType()))
                else:
                    from .types import FloatType
                    schema.append((expr.name, FloatType()))
            elif isinstance(expr, LiteralExpression):
                if isinstance(expr.value, int):
                    from .types import IntegerType
                    schema.append(("literal", IntegerType()))
                elif isinstance(expr.value, float):
                    from .types import FloatType
                    schema.append(("literal", FloatType()))
                else:
                    from .types import TextType
                    schema.append(("literal", TextType()))
            else:
                from .types import TextType
                schema.append(("expr", TextType()))

        return schema

    def _has_aggregates(self, expressions: List[Expression]) -> bool:
        """Check if any expression contains aggregate functions.

        Args:
            expressions: List of expressions to check.

        Returns:
            True if any aggregate function is found.
        """
        for expr in expressions:
            if self._expr_has_aggregates(expr):
                return True
        return False

    def _expr_has_aggregates(self, expr: Expression) -> bool:
        """Recursively check if an expression contains aggregate functions.

        Args:
            expr: Expression to check.

        Returns:
            True if aggregate function is found.
        """
        if isinstance(expr, FunctionCall):
            if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                return True
        if isinstance(expr, BinaryExpression):
            return self._expr_has_aggregates(expr.left) or self._expr_has_aggregates(expr.right)
        if isinstance(expr, UnaryExpression):
            return self._expr_has_aggregates(expr.operand)
        if isinstance(expr, CaseExpression):
            for c in expr.conditions:
                if self._expr_has_aggregates(c):
                    return True
            for r in expr.results:
                if self._expr_has_aggregates(r):
                    return True
            if expr.else_result and self._expr_has_aggregates(expr.else_result):
                return True
        return False

    def _calculate_cost(self, node: PlanNode) -> float:
        """Calculate total cost of a plan tree.

        Args:
            node: Root plan node.

        Returns:
            Total estimated cost.
        """
        total = node.cost
        for child in node.children:
            total += self._calculate_cost(child)
        return total
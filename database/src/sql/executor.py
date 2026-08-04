"""Query executor for AinosDB SQL engine.

Implements a volcano-style iterator model for executing query plans.
Each plan node is an iterator that produces rows on demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union
from .planner import PlanNode, PlanNodeType, QueryPlan
from .parser import (
    Expression, LiteralExpression, ColumnExpression, BinaryExpression,
    UnaryExpression, FunctionCall, StarExpression, BetweenExpression,
    InExpression, LikeExpression, CaseExpression, SubqueryExpression,
    OrderByItem, ColumnDef,
)
from .catalog import Catalog, TableInfo, ColumnInfo
from .types import DataType, IntegerType, FloatType, TextType, BooleanType, parse_type_string
from .transaction import Transaction, TransactionManager


class ExecutionContext:
    """Context for query execution.

    Provides access to the catalog, storage engine, and transaction state.

    Attributes:
        catalog: System catalog.
        transaction_manager: Transaction manager.
        data_store: Data storage interface.
        vector_store: Vector index interface.
        doc_store: Document store interface.
    """

    def __init__(
        self,
        catalog: Catalog,
        transaction_manager: Optional[TransactionManager] = None,
        data_store: Any = None,
        vector_store: Any = None,
        doc_store: Any = None,
    ) -> None:
        self.catalog = catalog
        self.transaction_manager = transaction_manager
        self.data_store = data_store
        self.vector_store = vector_store
        self.doc_store = doc_store
        self.current_transaction: Optional[Transaction] = None

    def get_table_data(self, table_name: str) -> List[Dict[str, Any]]:
        """Get all rows from a table.

        Args:
            table_name: Table name.

        Returns:
            List of row dictionaries.
        """
        if self.data_store is not None:
            return self.data_store.get_table_data(table_name)
        return []

    def insert_row(self, table_name: str, row: Dict[str, Any]) -> None:
        """Insert a row into a table.

        Args:
            table_name: Table name.
            row: Row data as dictionary.
        """
        if self.data_store is not None:
            self.data_store.insert_row(table_name, row)

    def delete_rows(self, table_name: str, condition: Any) -> int:
        """Delete rows from a table.

        Args:
            table_name: Table name.
            condition: Predicate function or expression.

        Returns:
            Number of deleted rows.
        """
        if self.data_store is not None:
            return self.data_store.delete_rows(table_name, condition)
        return 0

    def update_rows(self, table_name: str, set_clauses: Any, condition: Any) -> int:
        """Update rows in a table.

        Args:
            table_name: Table name.
            set_clauses: Column-value pairs to update.
            condition: Predicate function or expression.

        Returns:
            Number of updated rows.
        """
        if self.data_store is not None:
            return self.data_store.update_rows(table_name, set_clauses, condition)
        return 0


class Executor:
    """Query executor using volcano-style iteration.

    Each plan node type has a corresponding execute method that
    returns an iterator of result rows.

    Attributes:
        context: Execution context with catalog and storage access.
    """

    def __init__(self, context: ExecutionContext) -> None:
        self.context = context

    def execute(self, plan: QueryPlan) -> List[Dict[str, Any]]:
        """Execute a query plan and return all results.

        Args:
            plan: The query plan to execute.

        Returns:
            List of result rows as dictionaries.
        """
        results = list(self._execute_node(plan.root))
        return results

    def execute_iterator(self, plan: QueryPlan) -> Iterator[Dict[str, Any]]:
        """Execute a query plan and return an iterator over results.

        Args:
            plan: The query plan to execute.

        Yields:
            Result rows as dictionaries.
        """
        yield from self._execute_node(plan.root)

    def _execute_node(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a plan node and produce rows.

        Args:
            node: Plan node to execute.

        Yields:
            Result rows as dictionaries.
        """
        dispatch = {
            PlanNodeType.SEQUENTIAL_SCAN: self._execute_scan,
            PlanNodeType.INDEX_SCAN: self._execute_index_scan,
            PlanNodeType.FILTER: self._execute_filter,
            PlanNodeType.PROJECTION: self._execute_projection,
            PlanNodeType.INSERT: self._execute_insert,
            PlanNodeType.CREATE_TABLE: self._execute_create_table,
            PlanNodeType.CREATE_DATABASE: self._execute_create_database,
            PlanNodeType.DROP_TABLE: self._execute_drop_table,
            PlanNodeType.DROP_DATABASE: self._execute_drop_database,
            PlanNodeType.DELETE: self._execute_delete,
            PlanNodeType.UPDATE: self._execute_update,
            PlanNodeType.NESTED_LOOP_JOIN: self._execute_nested_loop_join,
            PlanNodeType.SORT: self._execute_sort,
            PlanNodeType.LIMIT: self._execute_limit,
            PlanNodeType.AGGREGATE: self._execute_aggregate,
            PlanNodeType.DISTINCT: self._execute_distinct,
            PlanNodeType.EXPLAIN: self._execute_explain,
            PlanNodeType.USE_DATABASE: self._execute_use,
            PlanNodeType.SHOW: self._execute_show,
            PlanNodeType.TRANSACTION: self._execute_transaction,
            PlanNodeType.ALTER_TABLE: self._execute_alter_table,
            PlanNodeType.VECTOR_INDEX_SCAN: self._execute_vector_scan,
            PlanNodeType.DOCUMENT_SCAN: self._execute_document_scan,
        }

        handler = dispatch.get(node.node_type)
        if handler is None:
            raise ValueError(f"Unknown plan node type: {node.node_type}")

        yield from handler(node)

    def _execute_scan(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a sequential scan of a table.

        Args:
            node: Scan plan node.

        Yields:
            Row dictionaries from the table.
        """
        table_name = node.table_name
        if table_name is None:
            return

        table_info = self.context.catalog.get_table(table_name)
        if table_info is None:
            raise ValueError(f"Table '{table_name}' not found")

        rows = self.context.get_table_data(table_name)
        for row in rows:
            yield row

    def _execute_index_scan(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an index scan.

        For now, falls back to sequential scan.

        Args:
            node: Index scan plan node.

        Yields:
            Row dictionaries from the table.
        """
        yield from self._execute_scan(node)

    def _execute_filter(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a filter (WHERE clause).

        Args:
            node: Filter plan node.

        Yields:
            Rows that pass the filter condition.
        """
        if not node.children:
            return

        child_iter = self._execute_node(node.children[0])

        for row in child_iter:
            if node.where_clause is None or self._evaluate_expression(node.where_clause, row):
                yield row

    def _execute_projection(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a projection (SELECT columns).

        Args:
            node: Projection plan node.

        Yields:
            Rows with only the selected columns.
        """
        if not node.children:
            return

        child_iter = self._execute_node(node.children[0])

        for row in child_iter:
            projected = {}
            for expr in node.expressions:
                if isinstance(expr, StarExpression):
                    # All columns
                    projected.update(row)
                elif isinstance(expr, ColumnExpression):
                    name = expr.name
                    table_prefix = expr.table_name
                    if table_prefix:
                        # Find the column with table prefix
                        for col_name, col_value in row.items():
                            if col_name.upper() == f"{table_prefix}.{name}".upper() or col_name.upper() == name.upper():
                                projected[col_name] = col_value
                                break
                    else:
                        projected[name] = row.get(name)
                elif isinstance(expr, FunctionCall):
                    # Aggregate functions are handled by aggregate node
                    projected[expr.name] = self._evaluate_expression(expr, row)
                elif isinstance(expr, LiteralExpression):
                    projected["literal"] = expr.value
                else:
                    # General expression evaluation
                    projected[str(expr)] = self._evaluate_expression(expr, row)

            yield projected

    def _execute_insert(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an INSERT statement.

        Args:
            node: Insert plan node.

        Yields:
            Single row with insert result.
        """
        table_name = node.table_name
        if table_name is None:
            return

        table_info = self.context.catalog.get_table(table_name)
        if table_info is None:
            raise ValueError(f"Table '{table_name}' not found")

        inserted_count = 0
        for row_values in node.values:
            row = {}
            if node.columns:
                # Named columns
                for i, col_name in enumerate(node.columns):
                    if i < len(row_values):
                        expr = row_values[i]
                        row[col_name] = self._evaluate_expression(expr, row)
                # Handle default values for unnamed columns
                for col in table_info.columns:
                    if col.name not in row:
                        if col.default is not None:
                            row[col.name] = col.default
                        else:
                            row[col.name] = None
            else:
                # Positional values (all columns)
                for i, col in enumerate(table_info.columns):
                    if i < len(row_values):
                        expr = row_values[i]
                        row[col.name] = self._evaluate_expression(expr, row)
                    elif col.default is not None:
                        row[col.name] = col.default
                    else:
                        row[col.name] = None

            self.context.insert_row(table_name, row)
            self.context.catalog.update_row_count(table_name, 1)
            inserted_count += 1

        yield {"_inserted": inserted_count, "table": table_name}

    def _execute_create_table(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a CREATE TABLE statement.

        Args:
            node: Create table plan node.

        Yields:
            Single row with creation result.
        """
        columns = []
        primary_key = None

        for col_def in node.column_defs:
            col_info = ColumnInfo(
                name=col_def.name,
                data_type=parse_type_string(col_def.data_type),
                nullable=col_def.nullable,
                default=col_def.default,
                primary_key=col_def.primary_key,
                unique=col_def.unique,
            )
            columns.append(col_info)
            if col_def.primary_key:
                primary_key = col_def.name

        table_info = self.context.catalog.create_table(
            node.name,
            columns,
            primary_key=primary_key,
        )

        yield {"_created": f"TABLE {node.name}"}

    def _execute_create_database(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a CREATE DATABASE statement.

        Args:
            node: Create database plan node.

        Yields:
            Single row with creation result.
        """
        db_info = self.context.catalog.create_database(node.name)
        yield {"_created": f"DATABASE {node.name}"}

    def _execute_drop_table(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a DROP TABLE statement.

        Args:
            node: Drop table plan node.

        Yields:
            Single row with drop result.
        """
        try:
            self.context.catalog.drop_table(node.name)
            yield {"_dropped": f"TABLE {node.name}"}
        except ValueError as e:
            if not node.if_exists:
                raise
            yield {"_dropped": None}

    def _execute_drop_database(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a DROP DATABASE statement.

        Args:
            node: Drop database plan node.

        Yields:
            Single row with drop result.
        """
        try:
            self.context.catalog.drop_database(node.name)
            yield {"_dropped": f"DATABASE {node.name}"}
        except ValueError as e:
            if not node.if_exists:
                raise
            yield {"_dropped": None}

    def _execute_delete(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a DELETE statement.

        Args:
            node: Delete plan node.

        Yields:
            Single row with delete result.
        """
        table_name = node.table_name
        if table_name is None:
            return

        table_info = self.context.catalog.get_table(table_name)
        if table_info is None:
            raise ValueError(f"Table '{table_name}' not found")

        # Build a predicate function from the WHERE clause
        where_fn = self._build_predicate(node.where_clause)

        deleted = self.context.delete_rows(table_name, where_fn)
        self.context.catalog.update_row_count(table_name, -deleted)

        yield {"_deleted": deleted, "table": table_name}

    def _execute_update(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an UPDATE statement.

        Args:
            node: Update plan node.

        Yields:
            Single row with update result.
        """
        table_name = node.table_name
        if table_name is None:
            return

        table_info = self.context.catalog.get_table(table_name)
        if table_info is None:
            raise ValueError(f"Table '{table_name}' not found")

        # Build set clauses dict
        set_dict = {}
        for col_name, expr in node.set_clauses:
            set_dict[col_name] = expr

        # Build predicate
        where_fn = self._build_predicate(node.where_clause)

        # We need to evaluate expressions against the current row, so we'll
        # handle this in the data store
        updated = self.context.update_rows(table_name, set_dict, where_fn)
        yield {"_updated": updated, "table": table_name}

    def _execute_nested_loop_join(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a nested loop join.

        Args:
            node: Join plan node.

        Yields:
            Joined rows.
        """
        if not node.children:
            return

        left_iter = list(self._execute_node(node.children[0]))
        right_table_name = node.table_name

        right_rows = self.context.get_table_data(right_table_name) if right_table_name else []

        for left_row in left_iter:
            for right_row in right_rows:
                joined = {**left_row, **right_row}

                # Evaluate join condition
                if node.join_condition is None:
                    yield joined  # CROSS JOIN
                elif self._evaluate_expression(node.join_condition, joined):
                    yield joined

    def _execute_sort(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a sort (ORDER BY).

        Args:
            node: Sort plan node.

        Yields:
            Sorted rows.
        """
        if not node.children:
            return

        rows = list(self._execute_node(node.children[0]))

        if node.order_by:
            def sort_key(row: Dict[str, Any]) -> List[Any]:
                keys = []
                for item in node.order_by:
                    val = self._evaluate_expression(item.expression, row)
                    keys.append(val if val is not None else "")
                return keys

            reverse = any(
                item.direction.upper() == "DESC" for item in node.order_by
            )
            rows.sort(key=sort_key, reverse=reverse)

        yield from rows

    def _execute_limit(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a LIMIT / OFFSET.

        Args:
            node: Limit plan node.

        Yields:
            Rows within the limit/offset constraints.
        """
        if not node.children:
            return

        offset = node.offset_count or 0
        limit = node.limit_count

        for i, row in enumerate(self._execute_node(node.children[0])):
            if i < offset:
                continue
            if limit is not None and (i - offset) >= limit:
                break
            yield row

    def _execute_aggregate(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an aggregation (GROUP BY + aggregate functions).

        Args:
            node: Aggregate plan node.

        Yields:
            Aggregated rows.
        """
        if not node.children:
            return

        rows = list(self._execute_node(node.children[0]))

        if not rows:
            return

        if node.group_by:
            # Group rows
            groups: Dict[Tuple, List[Dict[str, Any]]] = {}
            for row in rows:
                key = tuple(
                    self._evaluate_expression(expr, row) for expr in node.group_by
                )
                if key not in groups:
                    groups[key] = []
                groups[key].append(row)

            # Apply aggregates to each group
            for group_key, group_rows in groups.items():
                result = {}
                for i, expr in enumerate(node.group_by):
                    if isinstance(expr, ColumnExpression):
                        result[expr.name] = group_key[i]

                for expr in node.expressions:
                    if isinstance(expr, FunctionCall):
                        result[expr.name] = self._evaluate_aggregate(
                            expr, group_rows
                        )

                # Apply HAVING filter
                if node.having:
                    if self._evaluate_expression(node.having, result):
                        yield result
                else:
                    yield result
        else:
            # No GROUP BY - single group
            result = {}
            for expr in node.expressions:
                if isinstance(expr, FunctionCall):
                    result[expr.name] = self._evaluate_aggregate(expr, rows)
                elif isinstance(expr, ColumnExpression):
                    # In no-group-by mode, column references without aggregates
                    # are not valid in standard SQL, but we'll include them
                    if rows:
                        result[expr.name] = rows[0].get(expr.name)

            if node.having:
                if self._evaluate_expression(node.having, result):
                    yield result
            else:
                yield result

    def _execute_distinct(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a DISTINCT operation.

        Args:
            node: Distinct plan node.

        Yields:
            Unique rows.
        """
        if not node.children:
            return

        seen: Set[Tuple] = set()
        for row in self._execute_node(node.children[0]):
            key = tuple(sorted(row.items()))
            if key not in seen:
                seen.add(key)
                yield row

    def _execute_explain(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an EXPLAIN statement.

        Args:
            node: Explain plan node.

        Yields:
            Query plan description.
        """
        lines = []
        if node.children:
            self._format_plan(node.children[0], 0, lines)
        yield {"QUERY PLAN": "\n".join(lines)}

    def _format_plan(self, node: PlanNode, depth: int, lines: List[str]) -> None:
        """Format a plan tree for display.

        Args:
            node: Plan node.
            depth: Current indentation depth.
            lines: Output lines list.
        """
        indent = "  " * depth
        line = f"{indent}{node.node_type.name}"
        if node.table_name:
            line += f" on {node.table_name}"
        if node.where_clause:
            line += f" [filter: {node.where_clause}]"
        line += f" (cost={node.cost:.2f}, rows={node.cardinality})"
        lines.append(line)

        for child in node.children:
            self._format_plan(child, depth + 1, lines)

    def _execute_use(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a USE statement.

        Args:
            node: Use database plan node.

        Yields:
            Single row with result.
        """
        if node.database_name:
            self.context.catalog.use_database(node.database_name)
            yield {"_result": f"Using database {node.database_name}"}

    def _execute_show(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a SHOW statement.

        Args:
            node: Show plan node.

        Yields:
            Rows with the requested information.
        """
        if node.object_type == "DATABASES":
            for db_name in self.context.catalog.list_databases():
                yield {"Database": db_name}
        elif node.object_type == "TABLES":
            for table_name in self.context.catalog.list_tables():
                yield {"Table": table_name}

    def _execute_transaction(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a transaction statement.

        Args:
            node: Transaction plan node.

        Yields:
            Single row with result.
        """
        if node.action == "BEGIN":
            if self.context.transaction_manager:
                self.context.current_transaction = (
                    self.context.transaction_manager.begin()
                )
            yield {"_result": "BEGIN"}
        elif node.action == "COMMIT":
            if self.context.current_transaction and self.context.transaction_manager:
                self.context.transaction_manager.commit(
                    self.context.current_transaction
                )
                self.context.current_transaction = None
            yield {"_result": "COMMIT"}
        elif node.action == "ROLLBACK":
            if self.context.current_transaction and self.context.transaction_manager:
                self.context.transaction_manager.rollback(
                    self.context.current_transaction
                )
                self.context.current_transaction = None
            yield {"_result": "ROLLBACK"}

    def _execute_alter_table(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute an ALTER TABLE statement.

        Args:
            node: Alter table plan node.

        Yields:
            Single row with result.
        """
        if node.action == "ADD COLUMN" and node.column_defs:
            col_def = node.column_defs[0]
            col_info = ColumnInfo(
                name=col_def.name,
                data_type=parse_type_string(col_def.data_type),
                nullable=col_def.nullable,
                default=col_def.default,
            )
            self.context.catalog.add_column(node.table_name, col_info)
            yield {"_altered": f"TABLE {node.table_name}, ADD COLUMN {col_def.name}"}
        elif node.action == "DROP COLUMN" and node.column_name:
            self.context.catalog.drop_column(node.table_name, node.column_name)
            yield {"_altered": f"TABLE {node.table_name}, DROP COLUMN {node.column_name}"}

    def _execute_vector_scan(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a vector index scan.

        Args:
            node: Vector scan plan node.

        Yields:
            Rows matching the vector search criteria.
        """
        if self.context.vector_store is not None and node.table_name:
            table_name = node.table_name
            query_vector = None
            k = 10

            if node.where_clause:
                # Extract vector search parameters from WHERE clause
                pass

            results = self.context.vector_store.search(table_name, query_vector, k)
            for row in results:
                yield row

    def _execute_document_scan(self, node: PlanNode) -> Iterator[Dict[str, Any]]:
        """Execute a document scan.

        Args:
            node: Document scan plan node.

        Yields:
            Matching documents.
        """
        if self.context.doc_store is not None and node.table_name:
            results = self.context.doc_store.query(
                node.table_name, node.where_clause
            )
            for doc in results:
                yield doc

    # --- Expression Evaluation ---

    def _evaluate_expression(
        self, expr: Expression, row: Dict[str, Any]
    ) -> Any:
        """Evaluate an expression against a row.

        Args:
            expr: Expression to evaluate.
            row: Current row data.

        Returns:
            Evaluated value.
        """
        if isinstance(expr, LiteralExpression):
            return expr.value

        elif isinstance(expr, ColumnExpression):
            # Try exact match first, then case-insensitive
            val = row.get(expr.name)
            if val is not None:
                return val
            # Case-insensitive lookup
            for k, v in row.items():
                if k.upper() == expr.name.upper():
                    return v
            return None

        elif isinstance(expr, BinaryExpression):
            left = self._evaluate_expression(expr.left, row)
            right = self._evaluate_expression(expr.right, row)

            if expr.operator == "=":
                return left == right
            elif expr.operator == "!=":
                return left != right
            elif expr.operator == "<":
                return left is not None and right is not None and left < right
            elif expr.operator == ">":
                return left is not None and right is not None and left > right
            elif expr.operator == "<=":
                return left is not None and right is not None and left <= right
            elif expr.operator == ">=":
                return left is not None and right is not None and left >= right
            elif expr.operator == "+":
                return left + right if left is not None and right is not None else None
            elif expr.operator == "-":
                return left - right if left is not None and right is not None else None
            elif expr.operator == "*":
                return left * right if left is not None and right is not None else None
            elif expr.operator == "/":
                if right == 0:
                    return None
                return left / right if left is not None and right is not None else None
            elif expr.operator == "AND":
                return bool(left) and bool(right)
            elif expr.operator == "OR":
                return bool(left) or bool(right)
            elif expr.operator == "IS":
                return left is right
            elif expr.operator == "IS NOT":
                return left is not right
            return None

        elif isinstance(expr, UnaryExpression):
            operand = self._evaluate_expression(expr.operand, row)
            if expr.operator == "NOT":
                return not bool(operand)
            elif expr.operator == "-":
                return -operand if operand is not None else None
            return operand

        elif isinstance(expr, FunctionCall):
            return self._evaluate_aggregate_function(expr, [row])

        elif isinstance(expr, BetweenExpression):
            val = self._evaluate_expression(expr.expr, row)
            low = self._evaluate_expression(expr.low, row)
            high = self._evaluate_expression(expr.high, row)
            return low <= val <= high

        elif isinstance(expr, InExpression):
            val = self._evaluate_expression(expr.expr, row)
            for v in expr.values:
                if self._evaluate_expression(v, row) == val:
                    return True
            return False

        elif isinstance(expr, LikeExpression):
            val = self._evaluate_expression(expr.expr, row)
            pattern = self._evaluate_expression(expr.pattern, row)
            if val is None or pattern is None:
                return False
            return self._match_like(str(val), str(pattern))

        elif isinstance(expr, CaseExpression):
            for i, cond in enumerate(expr.conditions):
                if self._evaluate_expression(cond, row):
                    return self._evaluate_expression(expr.results[i], row)
            if expr.else_result:
                return self._evaluate_expression(expr.else_result, row)
            return None

        elif isinstance(expr, StarExpression):
            return row

        elif isinstance(expr, SubqueryExpression):
            # For subqueries in expressions, execute and return scalar
            plan = self._create_subquery_plan(expr.statement)
            results = self.execute(plan)
            if results:
                return list(results[0].values())[0]
            return None

        return None

    def _evaluate_aggregate(
        self, expr: FunctionCall, rows: List[Dict[str, Any]]
    ) -> Any:
        """Evaluate an aggregate function over a list of rows.

        Args:
            expr: Aggregate function expression.
            rows: List of rows.

        Returns:
            Aggregated value.
        """
        name = expr.name.upper()

        if name == "COUNT":
            if expr.distinct:
                # COUNT(DISTINCT col)
                if expr.args:
                    values = set()
                    for arg in expr.args:
                        for row in rows:
                            val = self._evaluate_expression(arg, row)
                            values.add(val)
                    return len(values)
            return len(rows)

        # Extract values
        values = []
        for arg in expr.args:
            for row in rows:
                val = self._evaluate_expression(arg, row)
                if val is not None:
                    values.append(val)

        if not values:
            return None

        if name == "SUM":
            return sum(values)
        elif name == "AVG":
            return sum(values) / len(values)
        elif name == "MIN":
            return min(values)
        elif name == "MAX":
            return max(values)

        return None

    def _evaluate_aggregate_function(
        self, expr: FunctionCall, rows: List[Dict[str, Any]]
    ) -> Any:
        """Evaluate a function that may be aggregate or scalar.

        Args:
            expr: Function expression.
            rows: List of rows.

        Returns:
            Function result.
        """
        if expr.name.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            return self._evaluate_aggregate(expr, rows)
        return None

    def _build_predicate(
        self, where_clause: Optional[Expression]
    ) -> Any:
        """Build a predicate function from a WHERE clause.

        Args:
            where_clause: Optional WHERE expression.

        Returns:
            Predicate function or None.
        """
        if where_clause is None:
            return lambda row: True

        def predicate(row: Dict[str, Any]) -> bool:
            return bool(self._evaluate_expression(where_clause, row))

        return predicate

    def _match_like(self, value: str, pattern: str) -> bool:
        """Match a string against a LIKE pattern.

        Supports % and _ wildcards.

        Args:
            value: String to match.
            pattern: LIKE pattern.

        Returns:
            True if the value matches the pattern.
        """
        import re
        # Convert LIKE pattern to regex
        regex_parts = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == "%":
                regex_parts.append(".*")
            elif c == "_":
                regex_parts.append(".")
            elif c in ".^$*+?{}[]\\|()":
                regex_parts.append("\\" + c)
            else:
                regex_parts.append(c)
            i += 1

        regex = "^" + "".join(regex_parts) + "$"
        return bool(re.match(regex, value))

    def _create_subquery_plan(self, statement: Any) -> QueryPlan:
        """Create a plan for a subquery.

        Args:
            statement: Subquery statement.

        Returns:
            Query plan.
        """
        from .planner import Planner
        planner = Planner(self.context.catalog)
        return planner.create_plan(statement)
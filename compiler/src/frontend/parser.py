"""
AI 编译器工具链 - 语法分析器（递归下降）
"""

from __future__ import annotations

from typing import Optional, Any

from src.frontend.token import Token, TokenType
from src.frontend.ast import (
    ASTNode, IntegerLiteral, FloatLiteral, StringLiteral, BooleanLiteral,
    NullLiteral, Identifier, BinaryOp, UnaryOp, Assignment, Call, Access,
    ArrayLiteral, RecordLiteral, LambdaExpr, TernaryExpr, CastExpr,
    TypeAnnotation, ArrayType, TensorType, FunctionType,
    Parameter, VariableDecl, Block, IfStmt, WhileStmt, ForStmt, ForInStmt,
    BreakStmt, ContinueStmt, ReturnStmt, AssertStmt, DeferStmt, MatchStmt,
    ExpressionStmt, FunctionDecl, ClassDecl, ImportDecl, ExportDecl,
    TypeDecl, Module, Program, MatchPattern,
)
from src.utils.errors import ParserError, ErrorReporter


class Parser:
    """递归下降语法分析器"""

    def __init__(self, tokens: list[Token], file: str = "", error_reporter: Optional[ErrorReporter] = None):
        self.tokens: list[Token] = tokens
        self.file: str = file
        self.error_reporter: ErrorReporter = error_reporter or ErrorReporter()
        self.pos: int = 0
        self._loop_depth: int = 0  # 记录循环嵌套深度
        self._function_depth: int = 0  # 记录函数嵌套深度
        self.current_token: Token = self.tokens[0] if self.tokens else Token(TokenType.EOF, None, 0, 0, file)

    def parse(self) -> Program:
        """解析完整的程序"""
        modules = []
        while self._check(TokenType.IMPORT) or self._check(TokenType.CLASS, TokenType.FN, TokenType.LET, TokenType.CONST, TokenType.EXPORT, TokenType.TYPE, TokenType.PUBLIC, TokenType.PRIVATE, TokenType.EXTERN, TokenType.STATIC, TokenType.AT, TokenType.IDENTIFIER):
            module = self._parse_module()
            if module:
                modules.append(module)
        if not modules:
            # 创建默认模块
            decls = self._parse_declarations_until_eof()
            if decls:
                modules.append(Module("__main__", decls, self.file))
        return Program(modules)

    def parse_module(self) -> Module:
        """解析单个模块"""
        return self._parse_module()

    # ---------- 模块解析 ----------

    def _parse_module(self) -> Optional[Module]:
        """解析模块"""
        module_name = "__main__"
        declarations = self._parse_declarations_until_eof()
        if not declarations and self._check(TokenType.EOF):
            return None
        return Module(module_name, declarations, self.file)

    def _parse_declarations_until_eof(self) -> list[ASTNode]:
        """解析到文件末尾的所有声明"""
        declarations = []
        while not self._check(TokenType.EOF):
            try:
                decl = self._parse_declaration()
                if decl:
                    declarations.append(decl)
            except ParserError as e:
                self.error_reporter.report_error(e)
                self._synchronize()
            except Exception as e:
                self.error_reporter.report_error(
                    ParserError(f"解析错误: {e}", self.current_token.line, self.current_token.column, self.file)
                )
                self._synchronize()
        return declarations

    def _synchronize(self) -> None:
        """错误恢复: 跳过到下一个语句/声明的开头"""
        while not self._check(TokenType.EOF):
            if self._check(TokenType.SEMICOLON):
                self._advance()
                return
            if self._check(TokenType.LET, TokenType.CONST, TokenType.FN, TokenType.CLASS,
                           TokenType.IMPORT, TokenType.EXPORT, TokenType.TYPE, TokenType.RETURN,
                           TokenType.IF, TokenType.WHILE, TokenType.FOR, TokenType.BREAK,
                           TokenType.CONTINUE, TokenType.ASSERT, TokenType.DEFER, TokenType.MATCH):
                return
            if self._check(TokenType.LBRACE, TokenType.RBRACE):
                return
            self._advance()

    # ---------- 声明解析 ----------

    def _parse_declaration(self) -> Optional[ASTNode]:
        """解析声明"""
        if self._match(TokenType.IMPORT):
            return self._parse_import()
        if self._match(TokenType.EXPORT):
            return self._parse_export()
        if self._match(TokenType.PUBLIC):
            return self._parse_access_modifier_decl(True)
        if self._match(TokenType.PRIVATE):
            return self._parse_access_modifier_decl(False)
        if self._check(TokenType.AT):
            return self._parse_decorated_declaration()
        if self._match(TokenType.EXTERN):
            return self._parse_extern_declaration()
        if self._match(TokenType.STATIC):
            return self._parse_static_declaration()
        if self._match(TokenType.TYPE):
            return self._parse_type_decl()
        if self._match(TokenType.FN):
            return self._parse_function_decl(False)
        if self._match(TokenType.CLASS):
            return self._parse_class_decl(False)
        if self._match(TokenType.LET, TokenType.CONST):
            return self._parse_variable_decl()
        return self._parse_statement()

    def _parse_access_modifier_decl(self, is_public: bool) -> Optional[ASTNode]:
        """解析带访问修饰符的声明"""
        if self._check(TokenType.FN):
            self._advance()
            return self._parse_function_decl(is_public)
        if self._check(TokenType.CLASS):
            self._advance()
            return self._parse_class_decl(is_public)
        if self._check(TokenType.LET, TokenType.CONST):
            decl = self._parse_variable_decl()
            if decl:
                decl.is_exported = is_public
            return decl
        if self._check(TokenType.TYPE):
            self._advance()
            return self._parse_type_decl()
        self.error_reporter.report_error(
            ParserError("public/private 后需要 fn, class, let, const 或 type", self.current_token.line, self.current_token.column, self.file)
        )
        return None

    def _parse_decorated_declaration(self) -> Optional[ASTNode]:
        """解析带装饰器的声明"""
        decorators = []
        while self._match(TokenType.AT):
            decorator = self._parse_decorator()
            if decorator:
                decorators.append(decorator)
        if not decorators:
            return None
        if self._check(TokenType.FN):
            self._advance()
            decl = self._parse_function_decl(False)
            if decl:
                decl.decorators = decorators
            return decl
        if self._check(TokenType.CLASS):
            self._advance()
            decl = self._parse_class_decl(False)
            if decl:
                decl.decorators = decorators
            return decl
        self.error_reporter.report_error(
            ParserError("装饰器后需要函数或类声明", self.current_token.line, self.current_token.column, self.file)
        )
        return None

    def _parse_decorator(self) -> Optional[ASTNode]:
        """解析装饰器 @name 或 @name(args)"""
        if self._check(TokenType.IDENTIFIER):
            name = self._advance()
            if self._match(TokenType.LPAREN):
                args = self._parse_arguments()
                self._expect(TokenType.RPAREN, "装饰器参数后需要 )")
                return Call(Identifier(name.value, name, name.line, name.column, self.file), args, name, name.line, name.column, self.file)
            return Identifier(name.value, name, name.line, name.column, self.file)
        self.error_reporter.report_error(
            ParserError("装饰器后需要标识符", self.current_token.line, self.current_token.column, self.file)
        )
        return None

    def _parse_extern_declaration(self) -> Optional[ASTNode]:
        """解析外部声明"""
        if self._match(TokenType.FN):
            decl = self._parse_function_decl(False)
            if decl:
                decl.is_extern = True
            return decl
        self.error_reporter.report_error(
            ParserError("extern 后需要 fn", self.current_token.line, self.current_token.column, self.file)
        )
        return None

    def _parse_static_declaration(self) -> Optional[ASTNode]:
        """解析静态声明"""
        if self._check(TokenType.FN):
            self._advance()
            return self._parse_function_decl(False)
        self.error_reporter.report_error(
            ParserError("static 后需要 fn", self.current_token.line, self.current_token.column, self.file)
        )
        return None

    def _parse_import(self) -> ImportDecl:
        """解析 import 声明"""
        line = self.current_token.line
        col = self.current_token.column
        source = ""

        # import "module.ai" 或 import module_name
        if self._check(TokenType.STRING_LITERAL):
            module = self._advance().value
            source = module
        elif self._check(TokenType.IDENTIFIER):
            module = self._advance().value
            source = module
        else:
            raise ParserError("import 后需要模块名或字符串", self.current_token.line, self.current_token.column, self.file)

        names = []
        if self._match(TokenType.COLON_COLON):
            # import module::name1, name2
            while self._check(TokenType.IDENTIFIER):
                name = self._advance().value
                alias = None
                if self._match(TokenType.AS):
                    alias = self._expect(TokenType.IDENTIFIER, "as 后需要别名").value
                names.append((name, alias))
                if not self._match(TokenType.COMMA):
                    break
        elif self._match(TokenType.DOT):
            # import module.submodule
            module += "."
            while self._check(TokenType.IDENTIFIER):
                module += self._advance().value
                if self._match(TokenType.DOT):
                    module += "."
                else:
                    break

        self._expect(TokenType.SEMICOLON, "import 声明后需要 ;")
        return ImportDecl(module, names, source, line, col, self.file)

    def _parse_export(self) -> ExportDecl:
        """解析 export 声明"""
        line = self.current_token.line
        col = self.current_token.column
        decl = self._parse_declaration()
        if decl is None:
            raise ParserError("export 后需要声明", line, col, self.file)
        return ExportDecl(decl)

    def _parse_type_decl(self) -> TypeDecl:
        """解析类型别名声明"""
        line = self.current_token.line
        col = self.current_token.column
        name = self._expect(TokenType.IDENTIFIER, "type 后需要类型名称").value
        self._expect(TokenType.EQUAL, "类型别名声明需要 =")
        type_expr = self._parse_type()
        self._expect(TokenType.SEMICOLON, "类型声明后需要 ;")
        return TypeDecl(name, type_expr, line, col, self.file)

    def _parse_function_decl(self, is_exported: bool) -> FunctionDecl:
        """解析函数声明"""
        line = self.current_token.line
        col = self.current_token.column
        name = self._expect(TokenType.IDENTIFIER, "函数名").value

        # 泛型参数
        # 参数列表
        self._expect(TokenType.LPAREN, "函数参数列表需要 (")
        params = self._parse_parameters()
        self._expect(TokenType.RPAREN, "函数参数列表后需要 )")

        # 返回类型
        return_type = None
        if self._match(TokenType.ARROW):
            return_type = self._parse_type()

        # 函数体或外部声明
        body = Block([], line, col, self.file)
        if not self._check(TokenType.SEMICOLON):
            if self._check(TokenType.LBRACE):
                body = self._parse_block()
            else:
                # 单表达式函数体
                expr = self._parse_expression()
                body = Block([ReturnStmt(expr, None, line, col, self.file)], line, col, self.file)
                self._expect(TokenType.SEMICOLON, "函数表达式后需要 ;")
        else:
            self._advance()

        return FunctionDecl(name, params, return_type, body, is_exported, False, [], None, line, col, self.file)

    def _parse_class_decl(self, is_exported: bool) -> ClassDecl:
        """解析类声明"""
        line = self.current_token.line
        col = self.current_token.column
        name = self._expect(TokenType.IDENTIFIER, "类名").value

        # 基类
        base_class = None
        if self._match(TokenType.COLON):
            base_class = self._parse_type()

        # 类体
        self._expect(TokenType.LBRACE, "类声明需要 {")
        body = []
        while not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            member = self._parse_class_member()
            if member:
                body.append(member)
        self._expect(TokenType.RBRACE, "类体后需要 }")
        return ClassDecl(name, base_class, body, is_exported, [], None, line, col, self.file)

    def _parse_class_member(self) -> Optional[ASTNode]:
        """解析类成员"""
        if self._check(TokenType.PUBLIC):
            self._advance()
            return self._parse_class_member()
        if self._check(TokenType.PRIVATE):
            self._advance()
            return self._parse_class_member()
        if self._check(TokenType.STATIC):
            self._advance()
            return self._parse_class_member()
        if self._match(TokenType.LET, TokenType.CONST):
            return self._parse_variable_decl()
        if self._match(TokenType.FN):
            return self._parse_function_decl(False)
        return self._parse_statement()

    # ---------- 语句解析 ----------

    def _parse_statement(self) -> Optional[ASTNode]:
        """解析语句"""
        if self._check(TokenType.LBRACE):
            return self._parse_block()
        if self._match(TokenType.IF):
            return self._parse_if_stmt()
        if self._match(TokenType.WHILE):
            return self._parse_while_stmt()
        if self._match(TokenType.FOR):
            return self._parse_for_stmt()
        if self._match(TokenType.BREAK):
            return self._parse_break_stmt()
        if self._match(TokenType.CONTINUE):
            return self._parse_continue_stmt()
        if self._match(TokenType.RETURN):
            return self._parse_return_stmt()
        if self._match(TokenType.ASSERT):
            return self._parse_assert_stmt()
        if self._match(TokenType.DEFER):
            return self._parse_defer_stmt()
        if self._match(TokenType.MATCH):
            return self._parse_match_stmt()
        if self._check(TokenType.LET, TokenType.CONST):
            return self._parse_variable_decl()
        return self._parse_expression_statement()

    def _parse_block(self) -> Block:
        """解析语句块 { ... }"""
        line = self.current_token.line
        col = self.current_token.column
        self._expect(TokenType.LBRACE, "语句块需要 {")
        statements = []
        while not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)
        self._expect(TokenType.RBRACE, "语句块后需要 }")
        return Block(statements, line, col, self.file)

    def _parse_if_stmt(self) -> IfStmt:
        """解析 if 语句"""
        line = self.current_token.line
        col = self.current_token.column
        self._expect(TokenType.LPAREN, "if 条件需要 (")
        condition = self._parse_expression()
        self._expect(TokenType.RPAREN, "if 条件后需要 )")
        then_body = self._parse_statement() or Block([], line, col, self.file)
        else_body = None
        if self._match(TokenType.ELSE):
            else_body = self._parse_statement() or Block([], line, col, self.file)
        return IfStmt(condition, then_body, else_body, line, col, self.file)

    def _parse_while_stmt(self) -> WhileStmt:
        """解析 while 语句"""
        line = self.current_token.line
        col = self.current_token.column
        self._expect(TokenType.LPAREN, "while 条件需要 (")
        condition = self._parse_expression()
        self._expect(TokenType.RPAREN, "while 条件后需要 )")
        self._loop_depth += 1
        body = self._parse_statement() or Block([], line, col, self.file)
        self._loop_depth -= 1
        return WhileStmt(condition, body, line, col, self.file)

    def _parse_for_stmt(self) -> ASTNode:
        """解析 for 语句"""
        line = self.current_token.line
        col = self.current_token.column
        self._expect(TokenType.LPAREN, "for 后需要 (")

        # 初始化
        init = None
        if not self._check(TokenType.SEMICOLON):
            if self._check(TokenType.LET, TokenType.CONST):
                init = self._parse_variable_decl()
            else:
                init = self._parse_expression()
                self._expect(TokenType.SEMICOLON, "for 初始化后需要 ;")
        else:
            self._advance()  # 跳过 ;

        # 条件
        condition = None
        if not self._check(TokenType.SEMICOLON):
            condition = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "for 条件后需要 ;")

        # 更新
        update = None
        if not self._check(TokenType.RPAREN):
            update = self._parse_expression()
        self._expect(TokenType.RPAREN, "for 更新后需要 )")

        self._loop_depth += 1
        body = self._parse_statement() or Block([], line, col, self.file)
        self._loop_depth -= 1

        # 如果 init 是 VariableDecl 并且有 semicolon 已经消费了, 特殊处理
        if isinstance(init, VariableDecl):
            # init 已经是一个完整的声明
            pass
        elif init is not None:
            # init 是表达式，包装为 ExpressionStmt
            pass

        return ForStmt(init, condition, update, body, line, col, self.file)

    def _parse_break_stmt(self) -> BreakStmt:
        """解析 break 语句"""
        line = self.current_token.line
        col = self.current_token.column
        if self._loop_depth == 0:
            self.error_reporter.report_error(
                ParserError("break 只能在循环中使用", line, col, self.file)
            )
        self._expect(TokenType.SEMICOLON, "break 后需要 ;")
        return BreakStmt(None, line, col, self.file)

    def _parse_continue_stmt(self) -> ContinueStmt:
        """解析 continue 语句"""
        line = self.current_token.line
        col = self.current_token.column
        if self._loop_depth == 0:
            self.error_reporter.report_error(
                ParserError("continue 只能在循环中使用", line, col, self.file)
            )
        self._expect(TokenType.SEMICOLON, "continue 后需要 ;")
        return ContinueStmt(None, line, col, self.file)

    def _parse_return_stmt(self) -> ReturnStmt:
        """解析 return 语句"""
        line = self.current_token.line
        col = self.current_token.column
        value = None
        if not self._check(TokenType.SEMICOLON) and not self._check(TokenType.RBRACE):
            value = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "return 后需要 ;")
        return ReturnStmt(value, None, line, col, self.file)

    def _parse_assert_stmt(self) -> AssertStmt:
        """解析 assert 语句"""
        line = self.current_token.line
        col = self.current_token.column
        condition = self._parse_expression()
        message = None
        if self._match(TokenType.COMMA):
            message = self._parse_expression()
        self._expect(TokenType.SEMICOLON, "assert 后需要 ;")
        return AssertStmt(condition, message, line, col, self.file)

    def _parse_defer_stmt(self) -> DeferStmt:
        """解析 defer 语句"""
        line = self.current_token.line
        col = self.current_token.column
        call = self._parse_call()
        self._expect(TokenType.SEMICOLON, "defer 后需要 ;")
        return DeferStmt(call, line, col, self.file)

    def _parse_match_stmt(self) -> MatchStmt:
        """解析 match 语句"""
        line = self.current_token.line
        col = self.current_token.column
        target = self._parse_expression()
        self._expect(TokenType.LBRACE, "match 后需要 {")
        arms = []
        while not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            pattern = self._parse_match_pattern()
            guard = None
            if self._match(TokenType.IF):
                guard = self._parse_expression()
            self._expect(TokenType.FAT_ARROW, "match arm 后需要 =>")
            body = self._parse_statement() or Block([], line, col, self.file)
            if guard:
                arms.append((MatchPattern("guard", guard=guard), body))
            else:
                arms.append((pattern, body))
            if self._match(TokenType.COMMA):
                continue
        self._expect(TokenType.RBRACE, "match 后需要 }")
        return MatchStmt(target, arms, line, col, self.file)

    def _parse_match_pattern(self) -> ASTNode:
        """解析匹配模式"""
        line = self.current_token.line
        col = self.current_token.column
        if self._match(TokenType.UNDERSCORE):
            return MatchPattern("wildcard", "_", line=line, column=col, file=self.file)
        if self._check(TokenType.INTEGER, TokenType.FLOAT_LITERAL, TokenType.STRING_LITERAL, TokenType.TRUE, TokenType.FALSE, TokenType.NULL):
            token = self._advance()
            return MatchPattern("literal", token.value, line=line, column=col, file=self.file)
        if self._check(TokenType.IDENTIFIER):
            name = self._advance().value
            return MatchPattern("variable", name, line=line, column=col, file=self.file)
        raise ParserError("无效的匹配模式", line, col, self.file)

    def _parse_variable_decl(self) -> VariableDecl:
        """解析变量声明"""
        line = self.current_token.line
        col = self.current_token.column
        token = self.tokens[self.pos - 1]  # let 或 const
        mutable = token.type == TokenType.LET
        name = self._expect(TokenType.IDENTIFIER, "变量名").value

        # 类型注解
        type_annotation = None
        if self._match(TokenType.COLON):
            type_annotation = self._parse_type()

        # 初始化
        initializer = None
        if self._match(TokenType.EQUAL):
            initializer = self._parse_expression()

        self._expect(TokenType.SEMICOLON, "变量声明后需要 ;")
        return VariableDecl(name, type_annotation, initializer, mutable, False, token, line, col, self.file)

    def _parse_expression_statement(self) -> Optional[ASTNode]:
        """解析表达式语句"""
        if self._check(TokenType.SEMICOLON):
            self._advance()
            return None
        expr = self._parse_expression()
        # 检查非空表达式后的分号
        if not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            self._expect(TokenType.SEMICOLON, "表达式后需要 ;")
        return ExpressionStmt(expr, expr.line, expr.column)

    # ---------- 表达式解析 ----------

    def _parse_expression(self) -> ASTNode:
        """解析表达式（最低优先级）"""
        return self._parse_assignment()

    def _parse_assignment(self) -> ASTNode:
        """解析赋值表达式"""
        expr = self._parse_ternary()
        if self._check(TokenType.EQUAL, TokenType.PLUS_EQUAL, TokenType.MINUS_EQUAL,
                        TokenType.STAR_EQUAL, TokenType.SLASH_EQUAL, TokenType.PERCENT_EQUAL,
                        TokenType.AND_EQUAL, TokenType.OR_EQUAL, TokenType.XOR_EQUAL,
                        TokenType.LEFT_SHIFT_EQUAL, TokenType.RIGHT_SHIFT_EQUAL):
            op = self._advance()
            value = self._parse_assignment()
            return Assignment(expr, op, value, expr.line, expr.column, self.file)
        return expr

    def _parse_ternary(self) -> ASTNode:
        """解析三元表达式"""
        expr = self._parse_or()
        if self._match(TokenType.QUESTION):
            then_expr = self._parse_expression()
            self._expect(TokenType.COLON, "三元表达式需要 :")
            else_expr = self._parse_ternary()
            return TernaryExpr(expr, then_expr, else_expr, expr.line, expr.column, self.file)
        return expr

    def _parse_or(self) -> ASTNode:
        """解析逻辑或 ||"""
        expr = self._parse_and()
        while self._match(TokenType.OR):
            op = self.tokens[self.pos - 1]
            right = self._parse_and()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_and(self) -> ASTNode:
        """解析逻辑与 &&"""
        expr = self._parse_bit_or()
        while self._match(TokenType.AND):
            op = self.tokens[self.pos - 1]
            right = self._parse_bit_or()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_bit_or(self) -> ASTNode:
        """解析按位或 |"""
        expr = self._parse_bit_xor()
        while self._match(TokenType.BIT_OR):
            op = self.tokens[self.pos - 1]
            right = self._parse_bit_xor()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_bit_xor(self) -> ASTNode:
        """解析按位异或 ^"""
        expr = self._parse_bit_and()
        while self._match(TokenType.BIT_XOR):
            op = self.tokens[self.pos - 1]
            right = self._parse_bit_and()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_bit_and(self) -> ASTNode:
        """解析按位与 &"""
        expr = self._parse_equality()
        while self._match(TokenType.BIT_AND):
            op = self.tokens[self.pos - 1]
            right = self._parse_equality()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_equality(self) -> ASTNode:
        """解析相等性 ==, != """
        expr = self._parse_comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.NOT_EQUAL):
            op = self.tokens[self.pos - 1]
            right = self._parse_comparison()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_comparison(self) -> ASTNode:
        """解析比较 <, >, <=, >="""
        expr = self._parse_shift()
        while self._match(TokenType.LESS, TokenType.GREATER, TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL):
            op = self.tokens[self.pos - 1]
            right = self._parse_shift()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_shift(self) -> ASTNode:
        """解析移位 <<, >>"""
        expr = self._parse_term()
        while self._match(TokenType.LEFT_SHIFT, TokenType.RIGHT_SHIFT):
            op = self.tokens[self.pos - 1]
            right = self._parse_term()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_term(self) -> ASTNode:
        """解析项 +, -"""
        expr = self._parse_factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op = self.tokens[self.pos - 1]
            right = self._parse_factor()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_factor(self) -> ASTNode:
        """解析因子 *, /, %"""
        expr = self._parse_unary()
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self.tokens[self.pos - 1]
            right = self._parse_unary()
            expr = BinaryOp(expr, op, right, expr.line, expr.column, self.file)
        return expr

    def _parse_unary(self) -> ASTNode:
        """解析一元表达式"""
        if self._check(TokenType.MINUS, TokenType.NOT, TokenType.BIT_NOT, TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
            if self._check(TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
                # 前缀 ++/--
                op = self._advance()
                operand = self._parse_unary()
                return UnaryOp(op, operand, True, op.line, op.column, self.file)
            op = self._advance()
            operand = self._parse_unary()
            return UnaryOp(op, operand, True, op.line, op.column, self.file)
        return self._parse_postfix()

    def _parse_postfix(self) -> ASTNode:
        """解析后缀表达式"""
        expr = self._parse_primary()
        while True:
            if self._match(TokenType.LPAREN):
                # 函数调用
                args = self._parse_arguments()
                self._expect(TokenType.RPAREN, "参数列表后需要 )")
                expr = Call(expr, args, None, expr.line, expr.column, self.file)
            elif self._match(TokenType.DOT):
                # 属性访问
                key = self._parse_primary()
                expr = Access(expr, key, False, expr.line, expr.column, self.file)
            elif self._match(TokenType.LBRACKET):
                # 索引访问
                key = self._parse_expression()
                self._expect(TokenType.RBRACKET, "索引后需要 ]")
                expr = Access(expr, key, True, expr.line, expr.column, self.file)
            elif self._match(TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
                # 后缀 ++/--
                expr = UnaryOp(self.tokens[self.pos - 1], expr, False, expr.line, expr.column, self.file)
            else:
                break
        return expr

    def _parse_primary(self) -> ASTNode:
        """解析基本表达式"""
        line = self.current_token.line
        col = self.current_token.column

        if self._match(TokenType.LPAREN):
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN, "表达式后需要 )")
            return expr
        if self._match(TokenType.LBRACKET):
            return self._parse_array_literal(line, col)
        if self._match(TokenType.LBRACE):
            return self._parse_record_literal(line, col)
        if self._check(TokenType.INTEGER):
            token = self._advance()
            return IntegerLiteral(token.value, token, token.line, token.column, self.file)
        if self._check(TokenType.FLOAT_LITERAL):
            token = self._advance()
            return FloatLiteral(token.value, token, token.line, token.column, self.file)
        if self._check(TokenType.STRING_LITERAL):
            token = self._advance()
            return StringLiteral(token.value, token, token.line, token.column, self.file)
        if self._check(TokenType.CHAR_LITERAL):
            token = self._advance()
            return StringLiteral(token.value, token, token.line, token.column, self.file)
        if self._match(TokenType.TRUE):
            return BooleanLiteral(True, None, line, col, self.file)
        if self._match(TokenType.FALSE):
            return BooleanLiteral(False, None, line, col, self.file)
        if self._match(TokenType.NULL):
            return NullLiteral(None, line, col, self.file)
        if self._match(TokenType.LAMBDA, TokenType.FN):
            return self._parse_lambda(line, col)
        if self._match(TokenType.IDENTIFIER):
            token = self.tokens[self.pos - 1]
            return Identifier(token.value, token, token.line, token.column, self.file)
        if self._match(TokenType.UNDERSCORE):
            return Identifier("_", None, line, col, self.file)

        raise ParserError(f"意外的 token: {self.current_token}", self.current_token.line, self.current_token.column, self.file)

    def _parse_array_literal(self, line: int, col: int) -> ArrayLiteral:
        """解析数组字面量"""
        elements = []
        if not self._check(TokenType.RBRACKET):
            elements.append(self._parse_expression())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACKET):
                    break
                elements.append(self._parse_expression())
        self._expect(TokenType.RBRACKET, "数组字面量后需要 ]")
        return ArrayLiteral(elements, line, col, self.file)

    def _parse_record_literal(self, line: int, col: int) -> RecordLiteral:
        """解析记录字面量"""
        entries = []
        if not self._check(TokenType.RBRACE):
            key = self._parse_expression()
            if self._match(TokenType.COLON):
                val = self._parse_expression()
                entries.append((key, val))
            else:
                # 单个表达式，不是记录
                if entries:
                    pass
                return RecordLiteral([(key, key)], line, col, self.file)
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break
                key = self._parse_expression()
                self._expect(TokenType.COLON, "记录键值对需要 :")
                val = self._parse_expression()
                entries.append((key, val))
        self._expect(TokenType.RBRACE, "记录字面量后需要 }")
        if not entries:
            return RecordLiteral([], line, col, self.file)
        return RecordLiteral(entries, line, col, self.file)

    def _parse_lambda(self, line: int, col: int) -> LambdaExpr:
        """解析 Lambda 表达式"""
        params = []
        return_type = None

        if self._match(TokenType.LPAREN):
            params = self._parse_parameters()
            self._expect(TokenType.RPAREN, "lambda 参数后需要 )")
            if self._match(TokenType.ARROW):
                return_type = self._parse_type()
        else:
            # 单参数 lambda
            if self._check(TokenType.IDENTIFIER):
                token = self._advance()
                params.append(Parameter(token.value, None, None, False, token.line, token.column, self.file))

        self._expect(TokenType.FAT_ARROW, "lambda 需要 =>")
        body = self._parse_expression()
        return LambdaExpr(params, body, return_type, line, col, self.file)

    def _parse_arguments(self) -> list[ASTNode]:
        """解析函数调用参数列表"""
        args = []
        if not self._check(TokenType.RPAREN):
            args.append(self._parse_expression())
            while self._match(TokenType.COMMA):
                args.append(self._parse_expression())
        return args

    def _parse_parameters(self) -> list[Parameter]:
        """解析函数参数列表"""
        params = []
        if not self._check(TokenType.RPAREN):
            mutable = False
            if self._match(TokenType.MUT):
                mutable = True
            name = self._expect(TokenType.IDENTIFIER, "参数名").value
            type_annotation = None
            if self._match(TokenType.COLON):
                type_annotation = self._parse_type()
            default_value = None
            if self._match(TokenType.EQUAL):
                default_value = self._parse_expression()
            params.append(Parameter(name, type_annotation, default_value, mutable, self.current_token.line, self.current_token.column, self.file))
            while self._match(TokenType.COMMA):
                mutable = False
                if self._match(TokenType.MUT):
                    mutable = True
                name = self._expect(TokenType.IDENTIFIER, "参数名").value
                type_annotation = None
                if self._match(TokenType.COLON):
                    type_annotation = self._parse_type()
                default_value = None
                if self._match(TokenType.EQUAL):
                    default_value = self._parse_expression()
                params.append(Parameter(name, type_annotation, default_value, mutable, self.current_token.line, self.current_token.column, self.file))
        return params

    # ---------- 类型解析 ----------

    def _parse_type(self) -> ASTNode:
        """解析类型注解"""
        return self._parse_type_union()

    def _parse_type_union(self) -> ASTNode:
        """解析类型联合"""
        base = self._parse_type_function()
        while self._match(TokenType.BIT_OR):
            # 联合类型处理
            right = self._parse_type_function()
            base = TypeAnnotation("union", [base, right], base.line, base.column, self.file)
        return base

    def _parse_type_function(self) -> ASTNode:
        """解析函数类型"""
        # 检查是否是函数类型: (type, type) -> type
        if self._check(TokenType.LPAREN):
            # 需要前瞻确定是函数类型还是带括号的类型
            saved_pos = self.pos
            self._advance()
            if self._check(TokenType.RPAREN) or self._check(TokenType.IDENTIFIER, TokenType.INT, TokenType.FLOAT, TokenType.BOOL, TokenType.STRING, TokenType.VOID, TokenType.TENSOR, TokenType.ARRAY, TokenType.RECORD):
                param_types = []
                if not self._check(TokenType.RPAREN):
                    param_types.append(self._parse_type())
                    while self._match(TokenType.COMMA):
                        param_types.append(self._parse_type())
                self._expect(TokenType.RPAREN, "类型参数后需要 )")
                if self._match(TokenType.ARROW):
                    return_type = self._parse_type()
                    return FunctionType(param_types, return_type)
                # 不是函数类型，回退
                self.pos = saved_pos
                # 重新解析
                return self._parse_type_atom()
            self.pos = saved_pos
        return self._parse_type_atom()

    def _parse_type_atom(self) -> ASTNode:
        """解析基本类型"""
        line = self.current_token.line
        col = self.current_token.column

        if self._match(TokenType.INT):
            return TypeAnnotation("int", line=line, column=col, file=self.file)
        if self._match(TokenType.FLOAT):
            return TypeAnnotation("float", line=line, column=col, file=self.file)
        if self._match(TokenType.BOOL):
            return TypeAnnotation("bool", line=line, column=col, file=self.file)
        if self._match(TokenType.STRING):
            return TypeAnnotation("string", line=line, column=col, file=self.file)
        if self._match(TokenType.VOID):
            return TypeAnnotation("void", line=line, column=col, file=self.file)
        if self._match(TokenType.RECORD):
            return TypeAnnotation("record", line=line, column=col, file=self.file)
        if self._match(TokenType.ARRAY):
            if self._match(TokenType.LESS):
                element_type = self._parse_type()
                self._expect(TokenType.GREATER, "array 类型需要 >")
                return ArrayType(element_type, None, line, col, self.file)
            return TypeAnnotation("array", line=line, column=col, file=self.file)
        if self._match(TokenType.TENSOR):
            if self._match(TokenType.LESS):
                element_type = self._parse_type()
                shape = []
                while self._match(TokenType.COMMA):
                    if self._check(TokenType.LBRACKET):
                        # 形状数组 [d1, d2, ...]
                        self._advance()  # skip [
                        while not self._check(TokenType.RBRACKET) and not self._check(TokenType.EOF):
                            if self._check(TokenType.INTEGER):
                                token = self._advance()
                                shape.append(IntegerLiteral(token.value, token, token.line, token.column, self.file))
                            if not self._match(TokenType.COMMA):
                                break
                        self._expect(TokenType.RBRACKET, "tensor 形状数组需要 ]")
                    elif self._check(TokenType.INTEGER):
                        token = self._advance()
                        shape.append(IntegerLiteral(token.value, token, token.line, token.column, self.file))
                    else:
                        break
                self._expect(TokenType.GREATER, "tensor 类型需要 >")
                return TensorType(element_type, shape, line, col, self.file)
            return TypeAnnotation("tensor", line=line, column=col, file=self.file)
        if self._check(TokenType.IDENTIFIER):
            name = self._advance().value
            type_params = []
            if self._match(TokenType.LESS):
                type_params.append(self._parse_type())
                while self._match(TokenType.COMMA):
                    type_params.append(self._parse_type())
                self._expect(TokenType.GREATER, "泛型类型需要 >")
            return TypeAnnotation(name, type_params, line, col, self.file)
        if self._match(TokenType.LPAREN):
            inner = self._parse_type()
            self._expect(TokenType.RPAREN, "类型括号需要 )")
            return inner
        if self._match(TokenType.MUT):
            return self._parse_type()

        raise ParserError(f"期望类型，但遇到 {self.current_token}", self.current_token.line, self.current_token.column, self.file)

    # ---------- 辅助方法 ----------

    def _check(self, *types: str) -> bool:
        """检查当前 token 是否匹配给定类型之一"""
        if self.pos >= len(self.tokens):
            return False
        return self.current_token.type in types

    def _match(self, *types: str) -> bool:
        """尝试匹配并消费 token"""
        if self._check(*types):
            self._advance()
            return True
        return False

    def _advance(self) -> Token:
        """前进到下一个 token，返回当前 token"""
        token = self.current_token
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = Token(TokenType.EOF, None, token.line, token.column, self.file)
        return token

    def _expect(self, token_type: str, context: str = "") -> Token:
        """期望特定 token 类型，否则报错"""
        if self._check(token_type):
            return self._advance()
        msg = f"期望 {token_type}"
        if context:
            msg += f" ({context})"
        msg += f"，但遇到 {self.current_token.type}"
        raise ParserError(msg, self.current_token.line, self.current_token.column, self.file)

    def _parse_call(self) -> ASTNode:
        """解析函数调用（用于 defer）"""
        return self._parse_postfix()


class ParserHelper:
    """语法分析辅助工具"""

    @staticmethod
    def parse_file(filepath: str, error_reporter: Optional[ErrorReporter] = None) -> Program:
        """从文件读取并解析"""
        from src.frontend.lexer import Lexer
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        lexer = Lexer(source, filepath, error_reporter)
        tokens = lexer.tokenize()
        parser = Parser(tokens, filepath, error_reporter)
        return parser.parse()

    @staticmethod
    def parse_source(source: str, file: str = "", error_reporter: Optional[ErrorReporter] = None) -> Program:
        """解析源代码字符串"""
        from src.frontend.lexer import Lexer
        lexer = Lexer(source, file, error_reporter)
        tokens = lexer.tokenize()
        parser = Parser(tokens, file, error_reporter)
        return parser.parse()
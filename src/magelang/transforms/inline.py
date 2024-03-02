
from ..ast import *

def inline(grammar: Grammar) -> Grammar:

    new_rules = []

    def rewriter(expr: Expr) -> Expr | None:
        if isinstance(expr, RefExpr):
            rule = grammar.lookup(expr.name)
            if rule.is_public or rule.is_extern:
                return
            assert(rule.expr is not None)
            new_expr = rule.expr.clone()
            new_expr.label = rule.name
            return rewrite_expr(new_expr, rewriter)

    for rule in grammar.rules:
        if rule.is_extern:
            new_rules.append(rule)
        if rule.is_public:
            assert(rule.expr is not None)
            new_rules.append(Rule(
                decorators=rule.decorators,
                flags=rule.flags,
                name=rule.name,
                type_name=rule.type_name,
                expr=rewrite_expr(rule.expr, rewriter)
            ))

    return Grammar(new_rules)

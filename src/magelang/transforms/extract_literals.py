from pathlib import Path
import json

from ..ast import *

def extract_literals(grammar: Grammar) -> Grammar:

    new_rules = []

    with open(Path(__file__).parent.parent / 'names.json', 'r') as f:
        names = json.load(f)

    literal_to_name: dict[str, str] = {}

    token_counter = 0
    def generate_token_name() -> str:
        nonlocal token_counter
        name = f'token_{token_counter}'
        token_counter += 1
        return name

    def str_to_name(text: str) -> str | None:
        if text[0].isalpha() and all(ch.isalnum() for ch in text[1:]):
            return f'{text}_keyword'
        elif len(text) <= 4:
            return '_'.join(names[ch] for ch in text)

    def rewriter(expr: Expr) -> Expr | None:
        if isinstance(expr, LitExpr):
            name = str_to_name(expr.text)
            if name is None:
                name = generate_token_name()
            if expr.text not in literal_to_name:
                literal_to_name[expr.text] = name
                new_rules.append(Rule(decorators=[], flags=PUBLIC | FORCE_TOKEN, name=name, expr=expr, type_name=string_rule_type))
            return RefExpr(name)

    for rule in grammar.rules:
        if grammar.is_parse_rule(rule):
            assert(rule.expr is not None)
            new_rules.append(Rule(decorators=rule.decorators, flags=rule.flags, name=rule.name, type_name=rule.type_name, expr=rewrite_expr(rule.expr, rewriter)))
        else:
            new_rules.append(rule)

    return Grammar(new_rules)


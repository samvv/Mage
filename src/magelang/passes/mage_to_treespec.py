
from typing import Iterable, cast
from magelang.helpers import get_field_name, infer_type, get_fields
from magelang.lang.mage.ast import *
from magelang.lang.treespec import *

def mage_to_treespec(
    grammar: MageGrammar,
    strong_enums: bool = False,
    include_hidden: bool = False
) -> Specs:

    field_counter = 0
    def generate_field_name() -> str:
        nonlocal field_counter
        name = f'field_{field_counter}'
        field_counter += 1
        return name

    def get_variant_name(expr: MageExpr, i: int) -> str:
        name = get_field_name(expr)
        return f'member_{i}'  if name is None else name

    def get_variants(expr: MageExpr) -> list[Variant]:
        out: list[Variant] = []
        def visit(expr: MageExpr) -> None:
            if isinstance(expr, MageChoiceExpr):
                for element in expr.elements:
                    visit(element)
                return
            if isinstance(expr, MageSeqExpr):
                names = []
                types = list()
                for element in expr.elements:
                    names.append(get_variant_name(element, len(out)))
                    types.append(infer_type(element, grammar))
                out.append(Variant('_'.join(names), TupleType(types)))
                return
            out.append(Variant(get_variant_name(expr, len(out)), infer_type(expr, grammar)))
        visit(expr)
        return out

    def get_field_members(expr: MageExpr) -> Iterable[Field]:
        return cast(Iterable[Field], filter(lambda element: isinstance(element, Field), get_fields(expr, grammar, include_hidden=include_hidden)))

    def rename_duplicate_members(members: list[Field]) -> list[Field]:
        taken = dict[str, int]()
        out = []
        for field in members:
            count = taken.get(field.name, 0)
            taken[field.name] = count + 1
            if count > 0:
                field.name = f'{field.name}_{count+1}'
        return out

    toplevel = []

    for rule in grammar.rules:
        if rule.is_extern or grammar.is_fragment(rule) or rule.is_skip:
            continue
        # only Rule(is_extern=True) can have an empty expression
        assert(rule.expr is not None)
        if grammar.is_token_rule(rule):
            toplevel.append(TokenSpec(rule.name, rule.type_name, grammar.is_static_token_rule(rule) if rule.expr is not None else False))
            continue
        if grammar.is_variant_rule(rule):
            # if strong_enums:
            #     toplevel.append(VariantSpec(rule.name, list(get_variants(rule.expr))))
            # else:
            #     toplevel.append(TypeSpec(rule.name, UnionType(list(ty for _, ty in get_variants(rule.expr)))))
            toplevel.append(EnumSpec(rule.name, list(get_variants(rule.expr))))
            continue
        field_counter = 0
        assert(rule.expr is not None)
        members = list(get_field_members(rule.expr))
        rename_duplicate_members(members)
        toplevel.append(NodeSpec(rule.name, members))

    toplevel.sort(key=lambda spec: spec.name)

    # specs.add(VariantSpec(None, 'keyword', list((rule.name, TokenType(rule.name)) for rule in grammar.rules if rule.is_keyword)))
    # specs.add(VariantSpec(None, 'token', list((spec.name, TokenType(spec.name)) for spec in specs if isinstance(spec, TokenSpec))))
    # specs.add(VariantSpec(None, 'node', list((spec.name, NodeType(spec.name)) for spec in specs if isinstance(spec, NodeSpec))))
    # specs.add(VariantSpec(None, 'syntax', [ ('node', VariantType('node')), ('token', VariantType('token')) ]))

    return Specs(toplevel)

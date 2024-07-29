
from typing import Iterator
from sweetener import Record, warn

from magelang.eval import accepts
from magelang.util import nonnull

from .ast import *

class Type(Record):
    pass

class AnyTokenType(Type):
    """
    Matches any token. Isn't used that often anymore.
    """
    pass

class AnyNodeType(Type):
    """
    Matches any node. Isn't used that often anymore.
    """
    pass

class ExternType(Type):
    """
    A type that is directly representing the Foo part in a `pub foo -> Foo = bar` 
    """
    name: str

class NodeType(Type):
    """
    Matches the type of a certain CST node.
    """
    name: str

class TokenType(Type):
    """
    Matches the type of a certain token.
    """
    name: str

class NeverType(Type):
    """
    Represents a type that never matches. Mostly useful to close off a union type when generating types.
    """
    pass

class TupleType(Type):
    element_types: list[Type]

class ListType(Type):
    element_type: Type

class UnionType(Type):
    types: list[Type]

class NoneType(Type):
    pass

class Field(Record):
    """
    Not a type, but represents exactly one field of a data structure/CST node. 
    """
    name: str
    ty: Type

class SpecBase(Record):
    pass

class TokenSpec(SpecBase):
    name: str
    field_type: str
    is_static: bool

class NodeSpec(SpecBase):
    name: str
    members: list[Field]

class VariantSpec(SpecBase):
    name: str
    members: list[str]

Spec = TokenSpec | NodeSpec | VariantSpec

class Specs:

    def __init__(self) -> None:
        self.mapping = dict[str, Spec]()

    def is_static(self, name: str) -> bool:
        spec = self.mapping.get(name)
        assert(isinstance(spec, TokenSpec))
        return spec.is_static

    def add(self, spec: Spec) -> None:
        assert(spec.name not in self.mapping)
        self.mapping[spec.name] = spec

    def lookup(self, name: str) -> Spec:
        spec = self.mapping.get(name)
        if spec is None:
            raise RuntimeError(f"could not find a CST specification for '{name}'")
        return spec

    def get_nodes(self) -> Iterator[NodeSpec]:
        for spec in self:
            if isinstance(spec, NodeSpec):
                yield spec

    def __iter__(self) -> Iterator[Spec]:
        return iter(self.mapping.values())

def make_optional(ty: Type) -> Type:
    return UnionType([ ty, NoneType() ])

def make_unit() -> Type:
    return TupleType([])

def is_unit(ty: Type) -> bool:
    return isinstance(ty, TupleType) and len(ty.element_types) == 0

def infer_type(grammar: Grammar, expr: Expr) -> Type:

    if isinstance(expr, HideExpr):
        return make_unit()

    if isinstance(expr, ListExpr):
        element_field = infer_type(grammar, expr.element)
        separator_field = infer_type(grammar, expr.separator)
        return ListType(TupleType([ element_field, make_optional(separator_field) ]))

    if isinstance(expr, RefExpr):
        rule = grammar.lookup(expr.name)
        if rule.is_extern:
            return TokenType(rule.name) if rule.is_token else NodeType(rule.name)
        if not rule.is_public:
            return infer_type(grammar, nonnull(rule.expr))
        return TokenType(expr.name) if grammar.is_token_rule(rule) else NodeType(expr.name)

    if isinstance(expr, LitExpr) or isinstance(expr, CharSetExpr):
        assert(False) # literals should already have been eliminated

    if isinstance(expr, RepeatExpr):
        element_type = infer_type(grammar, expr.expr)
        if expr.max == 0:
            return make_unit()
        elif expr.min == 0 and expr.max == 1:
            ty = make_optional(element_type)
        elif expr.min == 1 and expr.max == 1:
            ty = element_type
        else:
            ty = ListType(element_type)
        return ty

    if isinstance(expr, SeqExpr):
        types = []
        for element in expr.elements:
            ty = infer_type(grammar, element)
            if is_unit(ty):
                continue
            types.append(ty)
        if len(types) == 1:
            return types[0]
        return TupleType(types)

    if isinstance(expr, LookaheadExpr):
        return make_unit()

    if isinstance(expr, ChoiceExpr):
        types = list(infer_type(grammar, element) for element in expr.elements)
        # FIXME can't we just return an empty union type and normalize it afterwards?
        if len(types) == 0:
            return NeverType()
        if len(types) == 1:
            return types[0]
        return UnionType(types)

    raise RuntimeError(f'unexpected {expr}')

def flatten_union(ty: Type) -> Generator[Type, None, None]:
    if isinstance(ty, UnionType):
        for ty in ty.types:
            yield from flatten_union(ty)
    else:
        yield ty

def simplify_type(ty: Type) -> Type:
    if isinstance(ty, UnionType):
        new_tys = list(flatten_union(ty))
        if len(new_tys) == 0:
            return NeverType()
        if len(new_tys) == 1:
            return new_tys[0]
        return UnionType(new_tys)
    else:
        return ty

def grammar_to_specs(grammar: Grammar) -> Specs:

    field_counter = 0
    def generate_field_name() -> str:
        nonlocal field_counter
        name = f'field_{field_counter}'
        field_counter += 1
        return name

    def get_variant_members(expr: Expr) -> Generator[str, None, None]:
        if isinstance(expr, RefExpr):
            rule = grammar.lookup(expr.name)
            if rule.is_public:
                yield rule.name
                return
            # FIXME What to do with Rule(is_extern=True, is_public=False) ?
            if rule.expr is not None:
                yield from get_variant_members(rule.expr)
            return
        if isinstance(expr, ChoiceExpr):
            for element in expr.elements:
                yield from get_variant_members(element)
            return
        assert(False)

    def plural(name: str) -> str:
        return name if name.endswith('s') else f'{name}s'

    def get_field_name(expr: Expr) -> str:
        if isinstance(expr, RefExpr):
            return expr.label if expr.label is not None else expr.name
        if isinstance(expr, RepeatExpr):
            if expr.label is not None:
                return expr.label
            element_label = get_field_name(expr.expr)
            if element_label is not None:
                if expr.max > 1:
                    return plural(element_label)
                return element_label
            return generate_field_name()
        if isinstance(expr, ListExpr) or isinstance(expr, CharSetExpr) or isinstance(expr, ChoiceExpr):
            return expr.label if expr.label is not None else generate_field_name()
        raise RuntimeError(f'unexpected {expr}')

    def get_node_members(expr: Expr) -> Generator[Field, None, None]:

        if isinstance(expr, HideExpr) or isinstance(expr, LookaheadExpr):
            return

        if isinstance(expr, SeqExpr):
            for element in expr.elements:
                yield from get_node_members(element)
            return

        if isinstance(expr, LitExpr) or isinstance(expr, CharSetExpr):
            assert(False) # literals should already have been eliminated

        field_name = get_field_name(expr)
        field_type = simplify_type(infer_type(grammar, expr))
        expr.field_name = field_name
        expr.field_type = field_type
        yield Field(field_name, field_type)

    specs = Specs()

    for rule in grammar.rules:
        if rule.is_extern or grammar.is_fragment(rule) or rule.has_decorator('skip'):
            continue
        # only Rule(is_extern=True) can have an empty expression
        assert(rule.expr is not None)
        if grammar.is_token_rule(rule):
            specs.add(TokenSpec(rule.name, rule.type_name, grammar.is_static_token(rule.expr) if rule.expr is not None else False))
            continue
        if grammar.is_variant(rule):
            specs.add(VariantSpec(rule.name, list(get_variant_members(rule.expr))))
            continue
        field_counter = 0
        assert(rule.expr is not None)
        members = list(get_node_members(rule.expr))
        specs.add(NodeSpec(rule.name, members))

    kw_rules = []

    def visit(expr: Expr, rule: Rule) -> None:
        if isinstance(expr, LitExpr):
            match = False
            for rule in kw_rules:
                assert(rule.expr is not None)
                if accepts(rule.expr, expr.text, grammar):
                    match = True
            if match:
                specs.add(TokenSpec(rule.name, unit_rule_name, True))

    for rule in grammar.rules:
        if rule.expr is not None:
            for_each_expr(rule.expr, lambda expr: visit(expr, rule))

    return specs


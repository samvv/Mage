
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, assert_never, cast

from magelang.util import NameGenerator, to_snake_case

from .ast import *

type Type = ExternType | NodeType | TokenType | VariantType | NeverType | TupleType | ListType | PunctType | UnionType | NoneType | AnyType

class TypeBase:

    def __init__(self, before: list[Expr] | None = None, after: list[Expr] | None = None) -> None:
        if before is None:
            before = []
        if after is None:
            after = []
        self.after = after
        self.before = before

    @abstractmethod
    def encode(self) -> Any: ...

    def __lt__(self, value: object, /) -> bool:
        return isinstance(value, TypeBase) and self.encode() < value.encode()

    def __eq__(self, value: object, /) -> bool:
        return isinstance(value, TypeBase) and self.encode() == value.encode()

    def __hash__(self) -> int:
        return hash(self.encode())

class SpecType(TypeBase):
    name: str

class NodeType(SpecType):
    """
    Matches a leaf node in the AST/CST.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def encode(self) -> Any:
        return (1, self.name)

class TokenType(SpecType):
    """
    Matches a token type in the CST.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def encode(self) -> Any:
        return (2, self.name)

class VariantType(SpecType):
    """
    Matches a union of different nodes in the AST/CST.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def encode(self) -> Any:
        return (3, self.name)

class NeverType(TypeBase):
    """
    Represents a type that never matches. Mostly useful to close off a union type when generating types.
    """

    def encode(self) -> Any:
        return (4,)

class TupleType(TypeBase):
    """
    A type that allows values to contain a specific sequence of types.
    """

    def __init__(self, element_types: list[Type], before: list[Expr] | None = None, after: list[Expr] | None = None) -> None:
        super().__init__(before, after)
        self.element_types = element_types

    def derive(
        self,
        *,
        element_types: list[Type] | None = None,
        before: list[Expr] | None = None,
        after: list[Expr] | None = None
    ) -> 'TupleType':
        if element_types is None:
            element_types = list(self.element_types)
        if before:
            before = list(self.before)
        if after is None:
            after = list(self.after)
        return TupleType(element_types, before, after)


    def encode(self) -> Any:
        return (5, tuple(ty.encode() for ty in self.element_types))

class ListType(TypeBase):
    """
    A type that allows multiple values of the same underlying type.
    """

    def __init__(self, element_type: Type, required: bool, before: list[Expr] | None = None, after: list[Expr] | None = None) -> None:
        super().__init__(before, after)
        self.element_type = element_type
        self.required = required

    def derive(
        self,
        *,
        element_type: Type | None = None,
        required: bool | None = None,
        before: list[Expr] | None = None,
        after: list[Expr] | None = None
    ) -> 'ListType':
        if element_type is None:
            element_type = self.element_type
        if required is None:
            required = self.required
        if before:
            before = list(self.before)
        if after is None:
            after = list(self.after)
        return ListType(element_type, required, before, after)

    def encode(self) -> Any:
        return (6, self.element_type.encode(), self.required)

class PunctType(TypeBase):
    """
    A type that is like a list but where values are seperated by another type.
    """

    def __init__(
        self,
        element_type: Type,
        separator_type: Type,
        required: bool,
        before: list[Expr] | None = None,
        after: list[Expr] | None = None
    ) -> None:
        super().__init__(before, after)
        self.element_type = element_type
        self.separator_type = separator_type
        self.required = required

    def derive(
        self,
        *,
        element_type: Type | None = None,
        separator_type: Type | None = None,
        required: bool | None = None,
        before: list[Expr] | None = None,
        after: list[Expr] | None = None
    ) -> 'PunctType':
        if element_type is None:
            element_type = self.element_type
        if separator_type is None:
            separator_type = self.separator_type
        if required is None:
            required = self.required
        if before:
            before = list(self.before)
        if after is None:
            after = list(self.after)
        return PunctType(element_type, separator_type, required, before, after)

    def encode(self) -> Any:
        return (7, self.element_type.encode(), self.separator_type.encode(), self.required)

class UnionType(TypeBase):
    """
    A type where any of the member types are valid.
    """

    def __init__(self, types: list[Type], before: list[Expr] | None = None, after: list[Expr] | None = None) -> None:
        super().__init__(before, after)
        self.types = types

    def derive(
        self,
        *,
        types: list[Type] | None = None,
        before: list[Expr] | None = None,
        after: list[Expr] | None = None
    ) -> 'UnionType':
        if types is None:
            types = list(self.types)
        if before:
            before = list(self.before)
        if after is None:
            after = list(self.after)
        return UnionType(types, before, after)

    def encode(self) -> Any:
        return (8, tuple(ty.encode() for ty in self.types))

class NoneType(TypeBase):
    """
    A type that indicates that the value is empty.

    This type is usually created in conjunction with a union type.
    """

    def encode(self) -> Any:
        return (9,)

class ExternType(TypeBase):
    """
    A type that is directly representing the Foo part in a `pub foo -> Foo = bar` 
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def encode(self) -> Any:
        return (10, self.name)

class AnyType(TypeBase):
    """
    A type that is used as a placeholder when no more specific type is known.
    """

    def encode(self) -> Any:
        return (11,)

def rewrite_each_type(ty: Type, proc: Callable[[Type], Type | None]) -> Type:
    updated = proc(ty)
    if updated is not None:
        return updated
    if isinstance(ty, NoneType) \
        or isinstance(ty, AnyType) \
        or isinstance(ty, NeverType) \
        or isinstance(ty, SpecType) \
        or isinstance(ty, ExternType):
        return ty
    if isinstance(ty, ListType):
        new_element_type = rewrite_each_type(ty.element_type, proc)
        if new_element_type is ty.element_type:
            return ty
        return ty.derive(element_type=new_element_type)
    if isinstance(ty, PunctType):
        new_element_type = rewrite_each_type(ty.element_type, proc)
        new_separator_type = rewrite_each_type(ty.separator_type, proc)
        if new_element_type is ty.element_type and new_separator_type is ty.separator_type:
            return ty
        return ty.derive(element_type=new_element_type, separator_type=new_separator_type)
    if isinstance(ty, TupleType):
        new_types = list[Type]()
        changed = False
        for ty_2 in ty.element_types:
            new_ty_2 = rewrite_each_type(ty_2, proc)
            if new_ty_2 is not ty_2:
                changed = True
            new_types.append(new_ty_2)
        if not changed:
            return ty
        return ty.derive(element_types=new_types)
    if isinstance(ty, UnionType):
        new_types = list[Type]()
        changed = False
        for ty_2 in ty.types:
            new_ty_2 = rewrite_each_type(ty_2, proc)
            if new_ty_2 is not ty_2:
                changed = True
            new_types.append(new_ty_2)
        if not changed:
            return ty
        return ty.derive(types=new_types)
    assert_never(ty)


@dataclass
class Field:
    """
    Not a type, but represents exactly one field of a data structure/CST node. 
    """
    name: str
    ty: Type
    expr: Expr

@dataclass
class SpecBase:
    rule: Rule | None

@dataclass
class TokenSpec(SpecBase):
    name: str
    field_type: str
    is_static: bool

@dataclass
class NodeSpec(SpecBase):
    name: str
    fields: list[Field]

@dataclass
class VariantSpec(SpecBase):
    name: str
    members: list[tuple[str, Type]]

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

def is_optional(ty: Type) -> bool:
    if isinstance(ty, NoneType):
        return True
    if isinstance(ty, UnionType):
        for ty_2 in flatten_union(ty):
            if isinstance(ty_2, NoneType):
                return True
    return False

def make_unit() -> Type:
    return TupleType(list())

def is_unit(ty: Type) -> bool:
    return isinstance(ty, TupleType) and len(ty.element_types) == 0

def is_static(ty: Type, specs: Specs) -> bool:
    visited = set[str]()
    def visit(ty: Type) -> bool:
        if isinstance(ty, ExternType):
            return False
        if isinstance(ty, NeverType):
            return False
        if isinstance(ty, NoneType):
            return True
        if isinstance(ty, UnionType):
            return all(visit(ty_2) for ty_2 in ty.types)
        if isinstance(ty, VariantType):
            if ty.name in visited:
                return False
            visited.add(ty.name)
            spec = specs.lookup(ty.name)
            assert(isinstance(spec, VariantSpec))
            return all(visit(ty_2) for _, ty_2 in spec.members)
        if isinstance(ty, NodeType):
            if ty.name in visited:
                return False
            visited.add(ty.name)
            spec = specs.lookup(ty.name)
            assert(isinstance(spec, NodeSpec))
            return all(visit(field.ty) for field in spec.fields)
        if isinstance(ty, TokenType):
            if ty.name in visited:
                return False
            visited.add(ty.name)
            spec = specs.lookup(ty.name)
            assert(isinstance(spec, TokenSpec))
            return spec.is_static
        if isinstance(ty, TupleType):
            return all(visit(ty_2) for ty_2 in ty.element_types)
        if isinstance(ty, ListType):
            # This assumes that repetitions of a fixed size have been eliminated.
            return False
        if isinstance(ty, PunctType):
            return False
        if isinstance(ty, AnyType):
            return False
        assert_never(ty)
    return visit(ty)

def mangle_type(ty: Type) -> str:
    if isinstance(ty, NodeType):
        return f'node_{ty.name}'
    if isinstance(ty, VariantType):
        return f'variant_{ty.name}'
    if isinstance(ty, TokenType):
        return f'token_{ty.name}'
    if isinstance(ty, TupleType):
        out = f'tuple_{len(ty.element_types)}'
        for ty in ty.element_types:
            out += '_' + mangle_type(ty)
        return out
    if isinstance(ty, ListType):
        out = f'list_{mangle_type(ty.element_type)}'
        if ty.required:
            out += '_required'
        return out
    if isinstance(ty, ExternType):
        return f'extern_{to_snake_case(ty.name)}'
    if isinstance(ty, NeverType):
        return 'never'
    if isinstance(ty, NoneType):
        return 'none'
    if isinstance(ty, UnionType):
        out = f'union_{len(ty.types)}'
        for ty in ty.types:
            out += '_' + mangle_type(ty)
        return out
    if isinstance(ty, PunctType):
        out = f'punct_{mangle_type(ty.element_type)}_{mangle_type(ty.separator_type)}'
        if ty.required:
            out += '_required'
        return out
    if isinstance(ty, AnyType):
        return 'any'
    assert_never(ty)

def infer_type(expr: Expr, grammar: Grammar) -> Type:

    buffer = list()

    def visit(expr: Expr) -> Type:
        nonlocal buffer

        if isinstance(expr, HideExpr):
            buffer.append(expr.expr)
            # TODO return some internal constant rather than a public type
            return make_unit()

        if isinstance(expr, ListExpr):
            element_field = visit(expr.element)
            separator_field = visit(expr.separator)
            return PunctType(element_field, separator_field, expr.min_count > 0)

        if isinstance(expr, RefExpr):
            rule = grammar.lookup(expr.name)
            if rule is None:
                return AnyType()
            if rule.is_extern:
                return ExternType(rule.type_name) #TokenType(rule.name) if rule.is_token else NodeType(rule.name)
            if rule.expr is None:
                return AnyType()
            if not rule.is_public:
                return visit(rule.expr)
            if grammar.is_token_rule(rule):
                return TokenType(rule.name)
            if grammar.is_variant_rule(rule):
                return VariantType(rule.name)
            return NodeType(rule.name)

        if isinstance(expr, LitExpr) or isinstance(expr, CharSetExpr):
            assert(False) # literals should already have been eliminated

        if isinstance(expr, RepeatExpr):
            element_type = visit(expr.expr)
            if expr.max == 0:
                return make_unit()
            elif expr.min == 0 and expr.max == 1:
                ty = make_optional(element_type)
            elif expr.min == 1 and expr.max == 1:
                ty = element_type
            else:
                ty = ListType(element_type, expr.min > 0)
            return ty

        if isinstance(expr, SeqExpr):
            types = list()
            for element in expr.elements:
                ty = visit(element)
                if is_unit(ty):
                    continue
                ty.before.extend(buffer)
                buffer = []
                types.append(ty)
            if len(types) == 1:
                return types[0]
            return TupleType(types)

        if isinstance(expr, LookaheadExpr):
            return make_unit()

        if isinstance(expr, ChoiceExpr):
            return UnionType(list(visit(element) for element in expr.elements))

        assert_never(expr)

    ty = visit(expr)
    ty.after = buffer
    return ty

def flatten_union(ty: Type) -> Generator[Type, None, None]:
    if isinstance(ty, UnionType):
        for ty in ty.types:
            yield from flatten_union(ty)
    else:
        yield ty

def spec_to_type(spec: Spec) -> Type:
    if isinstance(spec, TokenSpec):
        return TokenType(spec.name)
    if isinstance(spec, NodeSpec):
        return NodeType(spec.name)
    if isinstance(spec, VariantSpec):
        return VariantType(spec.name)
    assert_never(spec)

def do_types_shallow_overlap(a: Type, b: Type) -> bool:
    """
    Determine whether two types have roughly the same structure.

    In Python, you could view this as whether the check `type(a) == type(b)`
    will always hold.
    """

    if isinstance(a, NeverType) or isinstance(b, NeverType):
        return False

    if isinstance(a, AnyType) or isinstance(b, AnyType):
        return True

    if isinstance(a, UnionType):
        return any(do_types_shallow_overlap(element_type, b) for element_type in a.types)

    if isinstance(b, UnionType):
        return do_types_shallow_overlap(b, a)

    if isinstance(a, ExternType) and isinstance(b, ExternType):
        return a.name == b.name

    if isinstance(a, NodeType) and isinstance(b, NodeType):
        return a.name == b.name

    if isinstance(a, VariantType) and isinstance(b, VariantType):
        return a.name == b.name

    if isinstance(a, TokenType) and isinstance(b, TokenType):
        return a.name == b.name

    if isinstance(a, ListType) and isinstance(b, ListType):
        return True

    if isinstance(a, PunctType) and isinstance(b, PunctType):
        return True

    if isinstance(a, NoneType) and isinstance(b, NoneType):
        return True

    if isinstance(a, TupleType) and isinstance(b, TupleType):
        return True

    return False

def expand_variant_types(ty: Type, *, specs: Specs) -> Type:
    def rewriter(ty: Type) -> Type | None:
        if isinstance(ty, VariantType):
            types = list()
            spec = specs.lookup(ty.name)
            assert(isinstance(spec, VariantSpec))
            for _, ty_2 in spec.members:
                types.append(rewrite_each_type(ty_2, rewriter))
            return UnionType(types, before=list(ty.before), after=list(ty.after))
    return rewrite_each_type(ty, rewriter)

def simplify_type(ty: Type) -> Type:
    if isinstance(ty, NoneType) \
        or isinstance(ty, NeverType) \
        or isinstance(ty, NodeType) \
        or isinstance(ty, ExternType) \
        or isinstance(ty, AnyType) \
        or isinstance(ty, VariantType) \
        or isinstance(ty, TokenType):
        return ty
    if isinstance(ty, ListType):
        return ty.derive(element_type=simplify_type(ty.element_type))
    if isinstance(ty, TupleType):
        return ty.derive(element_types=list(simplify_type(ty) for ty in ty.element_types))
    if isinstance(ty, PunctType):
        return ty.derive(
            element_type=simplify_type(ty.element_type),
            separator_type=simplify_type(ty.separator_type),
        )
    if isinstance(ty, UnionType):
        types = []
        for ty_2 in flatten_union(ty):
            if isinstance(ty_2, NeverType):
                continue
            if isinstance(ty_2, AnyType):
                return AnyType(before=list(ty_2.before), after=list(ty_2.after))
            types.append(simplify_type(ty_2))
        types.sort()
        iterator = iter(types)
        prev = next(iterator)
        dedup_types: list[Type] = list([ prev ])
        while True:
            try:
                curr = next(iterator)
            except StopIteration:
                break
            if prev == curr:
                continue
            dedup_types.append(curr)
            prev = curr
        if len(dedup_types) == 0:
            return NeverType()
        if len(dedup_types) == 1:
            return types[0]
        return ty.derive(types=dedup_types)
    assert_never(ty)

def is_type_assignable(left: Type, right: Type, *, specs: Specs) -> bool:
    if isinstance(left, NeverType) or isinstance(right, NeverType):
        return False
    if isinstance(left, AnyType) or isinstance(right, AnyType):
        return True
    if isinstance(left, NoneType) and isinstance(right, NoneType):
        return True
    if isinstance(left, ExternType) and isinstance(right, ExternType):
        return left.name == right.name
    if isinstance(left, NodeType) and isinstance(right, NodeType):
        return left.name == right.name
    if isinstance(left, TokenType) and isinstance(right, TokenType):
        return left.name == right.name
    if isinstance(left, VariantType):
        spec = specs.lookup(left.name)
        assert(isinstance(spec, VariantSpec))
        return all(is_type_assignable(ty, right, specs=specs) for _, ty in spec.members)
    if isinstance(right, VariantType):
        spec = specs.lookup(right.name)
        assert(isinstance(spec, VariantSpec))
        return any(is_type_assignable(left, ty, specs=specs) for _, ty in spec.members)
    if isinstance(left, ListType) and isinstance(right, ListType):
        return is_type_assignable(left.element_type, right.element_type, specs=specs)
    if isinstance(left, PunctType) and isinstance(right, ListType):
        return is_type_assignable(left.element_type, right.element_type, specs=specs) \
           and is_type_assignable(left.element_type, right.element_type, specs=specs)
    if isinstance(left, UnionType):
        return all(is_type_assignable(ty, right, specs=specs) for ty in left.types)
    if isinstance(right, UnionType):
        return any(is_type_assignable(left, ty, specs=specs) for ty in right.types)
    if isinstance(left, TupleType) and isinstance(right, TupleType):
        if len(left.element_types) != len(right.element_types):
            return False
        for a, b in zip(left.element_types, right.element_types):
            if not is_type_assignable(a, b, specs=specs):
                return False
        return True
    return False


def expand_type(ty: Type):
    if isinstance(ty, ListType):
        yield ty.element_type
    elif isinstance(ty, PunctType):
        yield ty.element_type
        yield ty.separator_type
    elif isinstance(ty, TupleType):
        for element_type in ty.element_types:
            yield element_type
    elif isinstance(ty, UnionType):
        for ty_2 in ty.types:
            yield ty_2

def contains_type(ty: Type, target_type: Type, *, specs: Specs) -> bool:
    if is_type_assignable(ty, target_type, specs=specs):
        return True
    for ty_2 in expand_type(ty):
        if contains_type(ty_2, target_type, specs=specs):
            return True
    return False

def is_cyclic(name: str, *, specs: Specs) -> bool:

    visited = set[str]()

    spec = specs.lookup(name)
    spec_type = expand_variant_types(spec_to_type(spec), specs=specs)

    def check(ty: Type, first = False) -> bool:

        # If the type is assignable to our original type, that means we have
        # detected a cycle.
        if not first and is_type_assignable(ty, spec_type, specs=specs):
            return True

        if isinstance(ty, NodeType):

            # We encountered this type before. This means that there is a
            # cycle, but it's not the cycle we are interested in.
            if ty.name in visited:
                return False

            visited.add(ty.name)

            spec = specs.lookup(ty.name)
            assert(isinstance(spec, NodeSpec))

            return any(check(expand_variant_types(field.ty, specs=specs)) for field in spec.fields)

        for ty_2 in expand_type(ty):
            if check(ty_2, first):
                return True
        return False

    return check(spec_type, first=True)

def merge_similar_types(ty: Type) -> Type:
    """
    Merges the elements of similarly structured types to a single type.

    For example, the type `List[int] | List[str]` becomes `List[int | str]`.

    Note that this is semantically incorrect, but some (mostly dynamic)
    programming languages can use this to write less intensive checks for a
    value that has this type.
    """

    # The resulting types that will be part of the output union type
    types = list[Type]()

    # Any types that should be inside of a `List[...]` type
    list_element_types = list[Type]()

    # `True` if all lists in the original type are required, `False` otherwise
    list_required = True

    # Any type that should go inside a `PunctType.element_type`
    punct_value_types = list[Type]()

    # Any type that should go inside a `PunctType.separator_type`
    punct_sep_types = list[Type]()

    # `True` if all punctuated types in the original type are required, `False`
    # otherwise
    punct_required = True

    # Holds tuples sorted by length, where each entry in the hash table
    # corresponds to another table that stores all possible elements for that
    # index.
    tuples_by_len = dict[int, list[list[Type]]]()\

    for ty_2 in flatten_union(ty):

        if isinstance(ty_2, TupleType):
            n = len(ty_2.element_types)
            if n not in tuples_by_len:
                new = list()
                for _ in range(0, n):
                    new.append(list())
                tuples_by_len[n] = new
            else:
                new = tuples_by_len[n]
            for i, ty_3 in enumerate(ty_2.element_types):
                new[i].append(merge_similar_types(ty_3))

        if isinstance(ty_2, ListType):
            list_element_types.append(merge_similar_types(ty_2.element_type))
            if not ty_2.required:
                list_required = False

        elif isinstance(ty_2, PunctType):
            punct_value_types.append(merge_similar_types(ty_2.element_type))
            punct_sep_types.append(merge_similar_types(ty_2.separator_type))
            if not ty_2.required:
                punct_required = False

        else:
            # If we got here, the type is not structural. In that case, we just
            # leave it as-is.
            types.append(ty_2)

    # Gather all list elements under a single `List[...]`, if any
    if list_element_types:
        types.append(ListType(UnionType(list_element_types), list_required))

    # Gather all punctuated types under a single `Punct[..., ....]`, if any
    if punct_value_types or punct_sep_types:
        assert(punct_value_types)
        assert(punct_sep_types)
        types.append(PunctType(UnionType(punct_value_types), UnionType(punct_sep_types), punct_required))

    # Gather all tuples, by traversing the hash table and freezing the elements that are stored together
    for tuple_elements in tuples_by_len.values():
        new_tuple_elements = list[Type]()
        for elements_at_index in tuple_elements:
            new_tuple_elements.append(UnionType(elements_at_index))
        types.append(TupleType(new_tuple_elements))

    # Some elements might be duplicated by the previous procedure, therefore we
    # call `simplify_type`.
    return simplify_type(UnionType(types))

def plural(name: str) -> str:
    return name if name.endswith('s') else f'{name}s'

def get_field_name(expr: Expr) -> str | None:
    if expr.label is not None:
        return expr.label
    if isinstance(expr, RefExpr):
        return expr.name
    if isinstance(expr, RepeatExpr):
        element_label = get_field_name(expr.expr)
        if element_label is not None:
            if expr.max > 1:
                return plural(element_label)
            return element_label
        return None
    if isinstance(expr, ListExpr) or isinstance(expr, CharSetExpr) or isinstance(expr, ChoiceExpr):
        return None
    raise RuntimeError(f'unexpected {expr}')

def get_fields(expr: Expr, grammar: Grammar, include_hidden: bool = False) -> Generator[Field | Expr, None, None]:

    generator = NameGenerator()

    def generate_field_name() -> str:
        return generator(prefix='field_')

    def visit(expr: Expr, rule_name: str | None) -> Generator[Field | Expr, None, None]:

        if isinstance(expr, LookaheadExpr):
            return

        if isinstance(expr, RefExpr):
            rule = grammar.lookup(expr.name)
            if rule is not None and rule.expr is not None and not rule.is_public:
                yield from visit(rule.expr, rule.name)
                return

        if isinstance(expr, HideExpr):
            if include_hidden:
                yield from visit(expr.expr, rule_name)
            else:
                yield expr.expr
            return

        if isinstance(expr, SeqExpr):
            for element in expr.elements:
                yield from visit(element, rule_name)
            return

        if isinstance(expr, LitExpr) or isinstance(expr, CharSetExpr):
            assert(False) # literals should already have been eliminated by previous passes

        field_name = rule_name or get_field_name(expr) or generate_field_name()
        field_type = simplify_type(infer_type(expr, grammar))
        expr.field_name = field_name
        expr.field_type = field_type
        yield Field(field_name, field_type, expr)

    return visit(expr, None)

def grammar_to_specs(grammar: Grammar, include_hidden = False) -> Specs:

    field_counter = 0
    def generate_field_name() -> str:
        nonlocal field_counter
        name = f'field_{field_counter}'
        field_counter += 1
        return name

    def get_member_name(expr: Expr) -> str:
        if expr.label is not None:
            return expr.label
        if isinstance(expr, RefExpr):
            rule = grammar.lookup(expr.name)
            if rule is None:
                return expr.name
            if not rule.is_public and rule.expr is not None:
                return get_member_name(rule.expr)
            return rule.name
        raise NotImplementedError()

    def get_variants(expr: Expr) -> Generator[tuple[str, Type], None, None]:
        if isinstance(expr, ChoiceExpr):
            for element in expr.elements:
                yield from get_variants(element)
            return
        if isinstance(expr, SeqExpr):
            names = []
            types = list()
            for element in expr.elements:
                names.append(get_member_name(element))
                types.append(infer_type(element, grammar))
            yield '_'.join(names), TupleType(types)
            return
        yield get_member_name(expr), infer_type(expr, grammar)

    def get_field_members(expr: Expr) -> Iterable[Field]:
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

    specs = Specs()

    for rule in grammar.rules:
        if rule.is_extern or grammar.is_fragment(rule) or rule.is_skip:
            continue
        # only Rule(is_extern=True) can have an empty expression
        assert(rule.expr is not None)
        if grammar.is_token_rule(rule):
            specs.add(TokenSpec(rule, rule.name, rule.type_name, grammar.is_static_token(rule.expr) if rule.expr is not None else False))
            continue
        if grammar.is_variant_rule(rule):
            specs.add(VariantSpec(rule, rule.name, list(get_variants(rule.expr))))
            continue
        field_counter = 0
        assert(rule.expr is not None)
        members = list(get_field_members(rule.expr))
        rename_duplicate_members(members)
        specs.add(NodeSpec(rule, rule.name, members))

    # specs.add(VariantSpec(None, 'keyword', list((rule.name, TokenType(rule.name)) for rule in grammar.rules if rule.is_keyword)))
    # specs.add(VariantSpec(None, 'token', list((spec.name, TokenType(spec.name)) for spec in specs if isinstance(spec, TokenSpec))))
    # specs.add(VariantSpec(None, 'node', list((spec.name, NodeType(spec.name)) for spec in specs if isinstance(spec, NodeSpec))))
    # specs.add(VariantSpec(None, 'syntax', [ ('node', VariantType('node')), ('token', VariantType('token')) ]))

    return specs



from typing import assert_never

from magelang.generator.python.util import build_cond, build_is_none, build_or, build_union, gen_deep_test, gen_initializers, gen_py_type, gen_shallow_test, namespaced, rule_type_to_py_type, to_py_class_name, quote_py_type, build_isinstance, PyCondCase
from magelang.treespec import *
from magelang.lang.python.cst import *
from magelang.lang.python.emitter import emit
from magelang.manager import Context

def mage_to_python_cst(
    grammar: MageGrammar,
    ctx: Context,
) -> PyModule:

    specs = grammar_to_specs(grammar)

    prefix= ctx.get_option('prefix')
    gen_parent_pointers = ctx.get_option('cst_parent_pointers')

    base_syntax_class_name = '_' + to_py_class_name('base_syntax', prefix)
    base_node_class_name = '_' + to_py_class_name('base_node', prefix)
    base_token_class_name = '_' + to_py_class_name('base_token', prefix)

    parent_nodes = dict[str, set[str]]()

    def name_to_type(name: str) -> Type:
        spec = specs.lookup(name)
        if isinstance(spec, VariantSpec):
            return VariantType(name)
        if isinstance(spec, NodeSpec):
            return NodeType(name)
        if isinstance(spec, TokenSpec):
            return TokenType(name)
        raise AssertionError()

    def get_parent_type(name: str) -> Type:
        if name not in parent_nodes:
            return NeverType()
        return UnionType(list(name_to_type(name) for name in sorted(parent_nodes[name])))

    def add_to_parent_nodes(name: str, ty: Type) -> None:
        if isinstance(ty, VariantType):
            spec = specs.lookup(ty.name)
            assert(isinstance(spec, VariantSpec))
            for _, member_type in spec.members:
                add_to_parent_nodes(name, member_type)
            return
        if isinstance(ty, NodeType) or isinstance(ty, TokenType):
            spec = specs.lookup(ty.name)
            if spec.name not in parent_nodes:
                parent_nodes[spec.name] = set()
            parent_nodes[spec.name].add(name)
        elif isinstance(ty, TupleType):
            for element in ty.element_types:
                add_to_parent_nodes(name, element)
        elif isinstance(ty, ListType) or isinstance(ty, PunctType):
            add_to_parent_nodes(name, ty.element_type)
        elif isinstance(ty, UnionType):
            for element in ty.types:
                add_to_parent_nodes(name, element)
        elif isinstance(ty, NoneType) or isinstance(ty, ExternType) or isinstance(ty, NeverType) or isinstance(ty, AnyType):
            pass
        else:
            assert_never(ty)

    if gen_parent_pointers:
        for spec in specs:
            if not isinstance(spec, NodeSpec):
                continue
            for field in spec.fields:
                add_to_parent_nodes(spec.name, field.ty)

    stmts: list[PyStmt] = [
        PyImportFromStmt(PyAbsolutePath(PyQualName('typing')), aliases=[
            PyFromAlias('Any'),
            PyFromAlias('TypeGuard'),
            PyFromAlias('Never'),
            PyFromAlias('Sequence'),
            PyFromAlias('no_type_check'),
        ]),
        PyImportFromStmt(PyAbsolutePath(PyQualName(modules=[ 'magelang' ], name='runtime')), aliases=[
            PyFromAlias('BaseNode'),
            PyFromAlias('BaseToken'),
            PyFromAlias('Punctuated'),
            PyFromAlias('Span'),
        ]),
        PyClassDef(base_node_class_name, bases=[ 'BaseNode' ], body=[
            PyPassStmt(),
        ]),
        PyClassDef(base_token_class_name, bases=[ 'BaseToken' ], body=[
            PyPassStmt(),
        ]),
    ]

    defs = {}

    for spec in specs:

        if not isinstance(spec, TokenSpec):
            continue

        body: list[PyStmt] = []

        if spec.is_static:

            body.append(PyPassStmt())

        else:

            init_body: list[PyStmt] = []

            init_body.append(PyExprStmt(expr=PyCallExpr(operator=PyAttrExpr(expr=PyCallExpr(operator=PyNamedExpr('super')), name='__init__'), args=[ (PyKeywordArg(name='span', expr=PyNamedExpr('span')), None) ])))

            params: list[PyParam] = []

            # self
            params.append(PyNamedParam(pattern=PyNamedPattern('self')))

            # value: Type
            params.append(PyNamedParam(pattern=PyNamedPattern('value'), annotation=rule_type_to_py_type(spec.field_type)))

            # span: Span | None = None
            params.append(PyNamedParam(pattern=PyNamedPattern('span'), annotation=build_union([ PyNamedExpr('Span'), PyNamedExpr('None') ]), default=PyNamedExpr('None')))

            # self.value = value
            init_body.append(PyAssignStmt(pattern=PyAttrPattern(pattern=PyNamedPattern('self'), name='value'), value=PyNamedExpr('value')))

            body.append(PyFuncDef(name='__init__', params=params, body=init_body))

        stmts.append(PyClassDef(name=to_py_class_name(spec.name, prefix), bases=[ base_token_class_name ], body=body))

    for spec in specs:

        if not isinstance(spec, NodeSpec):
            continue

        this_class_name = to_py_class_name(spec.name, prefix)

        body: list[PyStmt] = []
        params: list[PyParam] = []
        init_body: list[PyStmt] = []

        derive_params: list[PyParam] = [
            PyNamedParam(PyNamedPattern('self')),
        ]

        required: list[PyParam] = []
        optional: list[PyParam] = []

        for field in spec.fields:

            param_type, param_expr = gen_initializers(field.ty, PyNamedExpr(field.name), defs=defs, specs=specs, prefix=prefix)
            init_body.append(PyAssignStmt(
                pattern=PyAttrPattern(
                    pattern=PyNamedPattern('self'),
                    name=field.name
                ),
                annotation=gen_py_type(field.ty, prefix),
                value=param_expr,
            ))

            derive_params.append(PyNamedParam(
                pattern=PyNamedPattern(field.name),
                annotation=quote_py_type(gen_py_type(simplify_type(make_optional(param_type)), prefix=prefix)),
                default=PyNamedExpr('None'),
            ))

            param_type_str = emit(gen_py_type(param_type, prefix))

            if is_optional(param_type):
                optional.append(PyNamedParam(
                    pattern=PyNamedPattern(field.name),
                    annotation=PyConstExpr(literal=param_type_str),
                    default=PyNamedExpr('None')
                ))
            else:
                required.append(PyNamedParam(
                    pattern=PyNamedPattern(field.name),
                    annotation=PyConstExpr(param_type_str),
                ))

            if isinstance(field.ty, PunctType) or isinstance(field.ty, ListType):
                body.append(PyFuncDef(
                    name=f'count_{field.name}',
                    params=[ PyNamedParam(PyNamedPattern('self')) ],
                    return_type=PyNamedExpr('int'),
                    body=[
                        PyRetStmt(expr=PyCallExpr(PyNamedExpr('len'), args=[ PyAttrExpr(PyNamedExpr('self'), field.name) ])),
                    ]
                ))

        if not spec.fields:
            init_body.append(PyPassStmt())

        params.extend(required)
        if optional:
            params.append(PyKwSepParam())
            params.extend(optional)

        body.append(PyFuncDef(
            name='__init__',
            params=[ PyNamedParam(pattern=PyNamedPattern('self')), *params ],
            return_type=PyNamedExpr('None'),
            body=init_body
        ))

        derive_body = []
        derive_args = []

        for field in spec.fields:
            #coerce_type, coerce_expr = gen_initializers(field.ty, PyNamedExpr(field.name), specs=specs, defs=defs, prefix=prefix)
            derive_body.append(PyIfStmt(first=PyIfCase(
                test=build_is_none(PyNamedExpr(field.name)),
                body=[ PyAssignStmt(PyNamedPattern(field.name), value=PyAttrExpr(PyNamedExpr('self'), field.name)) ],
            )))
            derive_args.append(PyKeywordArg(field.name, PyNamedExpr(field.name)))
        derive_body.append(PyRetStmt(expr=PyCallExpr(PyNamedExpr(this_class_name), args=derive_args)))

        body.append(PyFuncDef(
             decorators=[ PyNamedExpr('no_type_check') ],
             name='derive',
             params=derive_params,
             return_type=PyConstExpr(this_class_name),
             body=derive_body,
         ))

        if gen_parent_pointers:
            parent_type_name = f'{to_py_class_name(spec.name, prefix)}Parent'
            # body.append(PyAssignStmt(PyNamedPattern('parent'), annotation=PyConstExpr(parent_type_name)))
            parent_type = get_parent_type(spec.name)
            parent_type_name = f'{to_py_class_name(spec.name, prefix)}Parent'
            # stmts.append(PyTypeAliasStmt(parent_type_name, gen_py_type(parent_type, prefix)))
            get_parent_body = []
            if isinstance(parent_type, NeverType):
                get_parent_body.append(PyRaiseStmt(PyCallExpr(PyNamedExpr('AssertionError'), args=[ PyConstExpr('trying to access the parent node of a top-level node') ])))
            else:
                get_parent_body.append(PyCallExpr(PyNamedExpr('assert'), args=[ PyInfixExpr(PyAttrExpr(PyNamedExpr('self'), '_parent'), (PyIsKeyword(), PyNotKeyword()), PyNamedExpr('None')) ]))
                get_parent_body.append(PyRetStmt(expr=PyAttrExpr(PyNamedExpr('self'), '_parent')))
            body.append(PyFuncDef(
                #decorators=[ PyDecorator(PyNamedExpr('property')) ],
                name='parent',
                params=[ PyNamedParam(PyNamedPattern('self')) ],
                return_type=PyConstExpr(parent_type_name),
                body=get_parent_body,
            ))

        stmts.append(PyClassDef(name=this_class_name, bases=[ base_node_class_name ], body=body))

    for spec in specs:

        if not isinstance(spec, VariantSpec):
            continue

        cls_name = to_py_class_name(spec.name, prefix)

        stmts.append(PyTypeAliasStmt(cls_name, build_union(gen_py_type(ty, prefix) for _, ty in spec.members)))

        params: list[PyParam] = []
        params.append(PyNamedParam(pattern=PyNamedPattern('value'), annotation=PyNamedExpr('Any')))
        stmts.append(PyFuncDef(
            name=f'is_{namespaced(spec.name, prefix)}',
            params=params,
            return_type=PySubscriptExpr(expr=PyNamedExpr('TypeGuard'), slices=[ PyNamedExpr(cls_name) ]),
            body=[
                PyRetStmt(expr=build_or(gen_deep_test(ty, PyNamedExpr('value'), prefix=prefix) for _, ty in spec.members))
            ],
        ))

    if gen_parent_pointers:
        for spec in specs:
            if not isinstance(spec, NodeSpec):
                continue
            parent_type = get_parent_type(spec.name)
            parent_type_name = f'{to_py_class_name(spec.name, prefix)}Parent'
            stmts.append(PyTypeAliasStmt(parent_type_name, gen_py_type(parent_type, prefix)))

    stmts.extend(defs.values())

    # Generate visitors

    proc_param_name = 'proc'
    node_param_name = 'node'

    def gen_visitor(name: str) -> PyFuncDef:

        generate_temporary = NameGenerator()

        main_spec = specs.lookup(name)
        main_type = spec_to_type(main_spec)

        body: list[PyStmt] = []

        def gen_each_field(spec: NodeSpec, target: PyExpr) -> Generator[PyStmt, None, None]:
            for field in spec.fields:
                if contains_type(field.ty, main_type, specs=specs):
                    yield from gen_proc_call(field.ty, PyAttrExpr(expr=target, name=field.name))

        def gen_proc_call(ty: Type, target: PyExpr) -> Generator[PyStmt, None, None]:
            if is_type_assignable(ty, main_type, specs=specs):
                yield PyExprStmt(PyCallExpr(operator=PyNamedExpr(proc_param_name), args=[ target ]))
                return
            if isinstance(ty, NoneType):
                return
            if isinstance(ty, ExternType):
                return
            if isinstance(ty, VariantType):
                spec = specs.lookup(ty.name)
                assert(isinstance(spec, VariantSpec))
                cases = []
                for _, ty_2 in spec.members:
                    body = list(gen_proc_call(ty_2, target))
                    if body:
                        cases.append((
                            gen_shallow_test(ty_2, target, prefix),
                            body
                        ))
                yield from build_cond(cases)
                return
            if isinstance(ty, NodeType):
                spec = specs.lookup(ty.name)
                assert(isinstance(spec, NodeSpec))
                yield from gen_each_field(spec, target)
                return
            if isinstance(ty, TokenType):
                return
            if isinstance(ty, TupleType):
                for i, element_type in enumerate(ty.element_types):
                    yield from gen_proc_call(element_type, PySubscriptExpr(expr=target, slices=[ PyConstExpr(literal=i) ]))
                return
            if isinstance(ty, ListType):
                element_name = generate_temporary(prefix='element')
                yield PyForStmt(pattern=PyNamedPattern(element_name), expr=target, body=list(gen_proc_call(ty.element_type, PyNamedExpr(element_name))))
                return
            if isinstance(ty, PunctType):
                element_name = generate_temporary(prefix='element')
                separator_name = generate_temporary(prefix='separator')
                yield PyForStmt(
                    pattern=PyTuplePattern(
                        elements=[
                            PyNamedPattern(element_name),
                            PyNamedPattern(separator_name)
                        ],
                    ),
                    expr=PyAttrExpr(target, 'elements'),
                    body=[
                        *gen_proc_call(ty.element_type, PyNamedExpr(element_name)),
                        *gen_proc_call(ty.separator_type, PyNamedExpr(separator_name)),
                    ]
                )
                yield PyIfStmt(first=PyIfCase(
                    test=PyInfixExpr(PyAttrExpr(target, 'last'), (PyIsKeyword(), PyNotKeyword()), PyNamedExpr('None')),
                    body=list(gen_proc_call(ty.element_type, PyAttrExpr(target, 'last')))
                ))
                return
            if isinstance(ty, UnionType):
                cases: list[PyCondCase] = []
                for element_type in ty.types:
                    body = list(gen_proc_call(element_type, target))
                    if body:
                        cases.append((
                            gen_shallow_test(element_type, target, prefix),
                            body
                        ))
                yield from build_cond(cases)
                return
            raise RuntimeError(f'unexpected {ty}')

        for spec in specs:

            if not is_type_assignable(spec_to_type(spec), main_type, specs=specs):
                continue

            if isinstance(spec, NodeSpec):

                # We're going to start a new scope, so all previous temporary names may be used once again
                generate_temporary.reset()

                if_body = list(gen_each_field(spec, PyNamedExpr(node_param_name)))
                if_body.append(PyRetStmt())
                body.append(PyIfStmt(first=PyIfCase(
                    test=PyCallExpr(
                        operator=PyNamedExpr('isinstance'),
                        args=[
                            PyNamedExpr(node_param_name),
                            PyNamedExpr(to_py_class_name(spec.name, prefix))
                        ]
                    ),
                    body=if_body
                )))

            elif isinstance(spec, TokenSpec):

                # body.append(PyExprStmt(PyCallExpr(operator=PyNamedExpr(proc_param_name), args=[ PyNamedExpr(node_param_name) ])))
                body.append(PyIfStmt(first=PyIfCase(
                    test=build_isinstance(
                        PyNamedExpr(node_param_name),
                        PyNamedExpr(to_py_class_name(spec.name, prefix))
                    ),
                    body=[
                        PyRetStmt(),
                    ],
                )))

        decorators = []
        if not debug:
            # We add `@typing.no_type_check` to drastically improve the performance of the type checker.
            decorators.append(PyDecorator(PyNamedExpr('no_type_check')))

        return PyFuncDef(
            decorators=decorators,
            name=f'for_each_{namespaced(name, prefix)}',
            params=[
                PyNamedParam(
                    PyNamedPattern(node_param_name),
                    annotation=PyNamedExpr(to_py_class_name(name, prefix))
                ),
                PyNamedParam(
                    PyNamedPattern(proc_param_name),
                    annotation=PySubscriptExpr(expr=PyNamedExpr('Callable'), slices=[ PyListExpr(elements=[ PyNamedExpr(to_py_class_name(name, prefix)) ]), PyNamedExpr('None') ])
                ),
            ],
            body=body,
        )

    variant_visitors = list(gen_visitor(spec.name) for spec in specs if isinstance(spec, VariantSpec) and is_cyclic(spec.name, specs=specs))

    stmts.extend([
        PyImportFromStmt(
            PyAbsolutePath('typing'),
            aliases=[
                PyFromAlias('Callable'),
                PyFromAlias('no_type_check'),
            ]
        ),
        PyImportFromStmt(
            PyRelativePath(dots=1, name=PyQualName('cst')),
            aliases=[ PyFromAlias(PyAsterisk()) ]
        ),
        *variant_visitors,
    ])

    variant_visitors = list(gen_visitor(spec.name) for spec in specs if isinstance(spec, VariantSpec) and is_cyclic(spec.name, specs=specs))

    return PyModule(stmts=stmts)


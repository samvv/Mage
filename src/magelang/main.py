
import argparse
from pathlib import Path

import templaty

from .scanner import Scanner
from .parser import Parser
from .repr import grammar_to_nodespec
from .prefix import transform as transform_prefix
from .reduce import transform as transform_reduce

project_dir = Path(__file__).parent.parent.parent
modules_dir = Path(__file__).parent
templates_dir = project_dir / 'templates'

# generators = dict()
# for path in (project_dir / 'templates').iterdir():
#     generators[path.stem] = importlib.import_module(f'magelang.codegen.{path.stem}')

def main():

    template_names = []
    for path in templates_dir.iterdir():
        if path.is_dir() and not str(path).startswith('_'):
            template_names.append(path.name)

    arg_parser = argparse.ArgumentParser()

    arg_parser.add_argument('file', nargs=1, help='A path to a grammar file')
    arg_parser.add_argument('template', choices=template_names, help='The name of the template to use')
    arg_parser.add_argument('--out-dir', default='output', help='Where to place the generated files')
 
    args = arg_parser.parse_args()

    file = args.file[0]
    dest_dir = Path(args.out_dir)

    with open(file, 'r') as f:
        text = f.read()
    scanner = Scanner(text, filename=file)
    parser = Parser(scanner)
    grammar = parser.parse_grammar()
    #grammar = transform_prefix(grammar)
    #grammar = transform_reduce(grammar)
    #visualize(grammar)

    ctx = {
        'grammar': grammar,
    }

    templaty.execute_dir(templates_dir / args.template, dest_dir=dest_dir, ctx=ctx)

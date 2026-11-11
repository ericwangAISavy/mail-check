"""Read-only static migration census. Does not import or start the application.

This is a coverage baseline, not evidence that any business feature is migrated.
Dynamic route registrations require separate runtime contract tests.
"""
import argparse
import ast
import json
from pathlib import Path
import re

METHODS={'get','post','put','patch','delete','head','options','api_route','websocket'}
CREATE_TABLE=re.compile(r'(?:^|;)\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)\s*\(',re.I)


def inventory(root:Path):
    root=Path(root);routes=[];tables={};unresolved=[]
    for path in sorted((root/'mailcheck').rglob('*.py')):
        relative=path.relative_to(root).as_posix()
        if 'services' in path.relative_to(root).parts:continue
        tree=ast.parse(path.read_text(encoding='utf-8'),filename=relative)
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                for name in CREATE_TABLE.findall(node.value):tables.setdefault(name,set()).add(relative)
            if '/web/' not in relative:continue
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not (isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute)
                            and decorator.func.attr in METHODS and decorator.args):continue
                    try:
                        route=ast.literal_eval(decorator.args[0])
                        method=decorator.func.attr
                        methods=['WEBSOCKET'] if method=='websocket' else [method.upper()]
                        if method=='api_route':
                            methods=next(ast.literal_eval(k.value) for k in decorator.keywords if k.arg=='methods')
                        if not isinstance(route,str) or not isinstance(methods,list) or not all(isinstance(m,str) for m in methods):raise ValueError
                    except (ValueError,TypeError,StopIteration):
                        unresolved.append({'source':relative,'handler':node.name,'expression':ast.unparse(decorator)})
                    else:routes.append({'source':relative,'handler':node.name,'path':route,'methods':sorted(methods)})
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'add_api_route','mount','include_router'}:
                unresolved.append({'source':relative,'handler':'registration','expression':ast.unparse(node)})
    return {'routes':sorted(routes,key=lambda r:(r['source'],r['path'],r['methods'],r['handler'])),
            'tables':[{'name':name,'sources':sorted(sources)} for name,sources in sorted(tables.items())],
            'manual_registration_review':unresolved,'business_ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    print(json.dumps(inventory(args.root),indent=2))


if __name__=='__main__':main()

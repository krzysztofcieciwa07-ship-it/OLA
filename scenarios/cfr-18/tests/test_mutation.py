import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/'ci/mutate.py'; spec=importlib.util.spec_from_file_location('m',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def test_same_seed_reproduces(): assert m.mutation('abc')==m.mutation('abc')
def test_different_seed_changes(): assert m.mutation('abc')!=m.mutation('xyz')

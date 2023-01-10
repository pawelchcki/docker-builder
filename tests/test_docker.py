import pytest
from docker_builder import dockerfile

def test_example():
    d = dockerfile("./example.Dockerfile")
    assert d != None
    assert d.build() == "66ba00ad3de8677a3fa4bc4ea0fc46ebca0f14db46ca365e7f60833068dd0148"
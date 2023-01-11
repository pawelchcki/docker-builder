import pytest
from pathlib import Path

import docker_builder

from docker_builder import dockerfile, set_project_root, Image, VirtualFile

tests_root = Path(__file__).parent
set_project_root(tests_root)

def test_basic_file_building():
    d = dockerfile("./basic.Dockerfile")
    assert "66ba00ad3de8677a3fa4bc4ea0fc46ebca0f14db46ca365e7f60833068dd0148" == d.build() 

def test_local_file_inclusion_and_isolation():
    isolated_implicit = dockerfile("./local_implicit_dependencies.Dockerfile").isolated_paths("./local_dependencies/A")
    non_isolated_implicit = dockerfile("./local_implicit_dependencies.Dockerfile")
    non_isolated_explicit = dockerfile("./local_explicit_dependencies.Dockerfile")
    # non isolated implicit dockerfile will pull in additional files
    assert isolated_implicit.build() != non_isolated_implicit.build()

    # explicitly listed dependencies (COPY /file /) copied into the image should result in exactly the same image
    # as implictly defined (COPY * /) if we use docker_builder to isolate the included files
    assert isolated_implicit.build() == non_isolated_explicit.build()
    
def test_extract_file_from_image():
    image = dockerfile("./local_explicit_dependencies.Dockerfile").image()
    image_built_from_alternative_root = dockerfile("./local_explicit_dependencies.Dockerfile", root_dir = tests_root / "local_dependencies/alternative_root").image()

    assert "A" == image.read_file_str("/A")
    assert "subfolder/A" == image_built_from_alternative_root.read_file_str("/A")
    
def test_create_artifact_only_image():
    base = Image("scratch")
    result = base.modify_image(append_paths_mapped={
        "/A": "local_dependencies/A",
        "/AA": VirtualFile("AA")
    })

    result.tag("test_create_artifact_only_dockerfile")
    # check if image can be accessed using only tag
    validation_image = Image("test_create_artifact_only_dockerfile")
    assert "A" == validation_image.read_file_str("/A")
    assert "AA" == validation_image.read_file_str("/AA")


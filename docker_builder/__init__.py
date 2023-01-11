import sys
import types
from pathlib import Path, PurePath
import inspect
import os
import tempfile
import subprocess
import shutil

# from utils import project_root
from pydoc import locate
import tarfile

import docker

project_root = Path(__file__).parent.parent


def set_project_root(new_root: str | Path):
    global project_root
    project_root = Path(new_root)


class VirtualFile(object):
    def __init__(self, contents):
        self.contents = contents
        self.tmp_file = tempfile.NamedTemporaryFile()
        self.tmp_file.write(self.contents.encode())
        self.tmp_file.seek(0)

    def path(self):
        return Path(self.tmp_file.name)


class Image(object):
    iid = str

    def __init__(self, iid):
        self.iid = iid

    def modify_image(
        self,
        append_from_image=None,
        append_paths=None,
        append_paths_mapped=None,
        env={},
    ):
        dockerfile_contents = ""

        if append_from_image:
            dockerfile_contents += f"FROM {append_from_image.iid} as source_image\n"

        dockerfile_contents += f"FROM {self.iid} as final_image\n"

        if append_from_image:
            dockerfile_contents += "COPY --from=source_image / /"

        if append_paths or append_paths_mapped:
            dockerfile_contents += "COPY / /\n"

        for k, v in env.items():
            dockerfile_contents += f"ENV {k} = {v}\n"

        d = Dockerfile(dockerfile_contents=dockerfile_contents)
        if append_paths:
            d.isolated_paths(*append_paths)
        if append_paths_mapped:
            d.isolated_paths_mapped(append_paths_mapped)

        new_iid = d.build()
        return Image(new_iid)

    def tag(self, tag):
        api = docker.from_env()
        image = api.images.get(self.iid)
        image.tag(tag)

    def _extract_files(self, paths=[]):
        dockerfile_contents = f"""
FROM {self.iid} as source_image
FROM scratch as target_image
"""
        for path in paths:
            dockerfile_contents += f"COPY --from=source_image {path} /\n"

        dockerfile = Dockerfile(dockerfile_contents=dockerfile_contents)
        dockerfile.isolated_paths()

        tmp_image = dockerfile.image()

        for layer in tmp_image._layers():
            for fname in layer.getnames():
                yield (fname, layer.extractfile(fname))

    def _save_image(self, target_path):
        api = docker.from_env()
        image = api.images.get(self.iid)
        with open(target_path, "wb") as output:
            for chunk in image.save():
                output.write(chunk)

    def _layers(self):
        with tempfile.NamedTemporaryFile() as tmp_image_file:
            self._save_image(tmp_image_file.name)
            t = tarfile.TarFile(fileobj=tmp_image_file)
            for fname in t.getnames():
                if fname.endswith("/layer.tar"):
                    reader = t.extractfile(fname)
                    yield tarfile.TarFile(fileobj=reader)

    def read_file(self, path):
        for _, reader in self._extract_files(paths=[path]):
            return reader.read()

    def read_file_str(self, path):
        return self.read_file(path).decode("utf-8")

    def __str__(self):
        return f"Image: {self.iid}"


class Dockerfile(object):
    dockerfile = Path
    root_dir = Path

    def __init__(
        self,
        dockerfile: Path | None = None,
        dockerfile_contents: str | None = None,
        root_dir=None,
    ):
        self.dockerfile = dockerfile
        self.virtual_files = []

        if dockerfile_contents and not dockerfile:
            dockerfile = VirtualFile(dockerfile_contents)
            self.virtual_files.append(dockerfile)
            self.dockerfile = dockerfile.path()

        if root_dir:
            self.root_dir = root_dir
        else:
            self.root_dir = project_root

        self.fs_dependencies = {}
        self.isolated_build = False

    def isolated_paths_mapped(self, mapped_paths):
        self.isolated_build = True
        root_dir = self.root_dir
        if not root_dir.is_absolute():
            parent = Path(inspect.stack()[1].filename).parent
            root_dir = parent / root_dir

        for target, src in mapped_paths.items():
            if isinstance(src, VirtualFile):
                self.virtual_files.append(src)
                src = src.path()
            src_path = Path(src)
            if not src_path.is_absolute():
                src_path = root_dir / src_path
            self.fs_dependencies[target] = src_path

        return self

    def isolated_paths(self, *paths):
        self.isolated_build = True
        root_dir = self.root_dir
        if not root_dir.is_absolute():
            parent = Path(inspect.stack()[1].filename).parent
            root_dir = parent / root_dir

        for path in paths:
            path = Path(path)
            self.fs_dependencies[path] = root_dir / path

        return self

    def _isolated_build(self, workdir_path, args):
        context_path = workdir_path / "context"
        os.makedirs(context_path)

        files_to_copy = {}
        for target, src in self.fs_dependencies.items():
            target = PurePath(target)
            if target.is_absolute():
                target = target.relative_to("/")
            files_to_copy[context_path / target] = src

        for target, _ in files_to_copy.items():
            path = target.parent
            os.makedirs(path, exist_ok=True)

        for target, src in files_to_copy.items():
            if src.is_file():
                shutil.copyfile(src, target, follow_symlinks=True)
                shutil.copymode(src, target, follow_symlinks=True)
            else:
                shutil.copytree(src, target)

        builder = _CLIBuilder(None)
        res = builder.build(context_path, dockerfile=self.dockerfile, buildargs=args)

        return res

    def build(self, args=None):
        if self.isolated_build:
            temp_dir = tempfile.TemporaryDirectory()
            return self._isolated_build(Path(temp_dir.name), args)
        else:
            builder = _CLIBuilder(None)
            return builder.build(
                self.root_dir, dockerfile=self.dockerfile, buildargs=args
            )

    def image(self):
        return Image(self.build())

    def __str__(self):
        return f"Image. Dockerfile: {self.dockerfile}"


def import_in_path_dockerfiles():
    caller_frame = inspect.stack()[1]
    caller_module = inspect.getmodule(caller_frame[0])

    path = Path(caller_module.__file__).parent
    files = list(
        filter(lambda path: path.lower().endswith(".dockerfile"), os.listdir(path))
    )

    for file in files:
        attr_name = file[: file.rfind(".")]
        dockerfile = Dockerfile(path / file)
        setattr(caller_module, attr_name, dockerfile)


def dockerfile(dockerfile, *args, **kwargs):
    dockerfile = Path(dockerfile)
    if not dockerfile.is_absolute():
        parent = Path(inspect.stack()[1].filename).parent
        dockerfile = parent / dockerfile

    return Dockerfile(dockerfile=dockerfile, *args, **kwargs)


class _CLIBuilder(object):
    def __init__(self, progress):
        self._progress = progress
        # TODO: this setting should not rely on global env
        self.quiet = False if os.getenv("DOCKER_QUIET") is None else True

    def build(
        self,
        path,
        tag=None,
        nocache=False,
        pull=False,
        forcerm=False,
        dockerfile=None,
        container_limits=None,
        buildargs=None,
        cache_from=None,
        target=None,
    ):

        if dockerfile:
            dockerfile = os.path.join(path, dockerfile)
        iidfile = tempfile.mktemp()

        command_builder = _CommandBuilder()
        command_builder.add_params("--build-arg", buildargs)
        command_builder.add_list("--cache-from", cache_from)
        command_builder.add_arg("--file", dockerfile)
        command_builder.add_flag("--force-rm", forcerm)
        command_builder.add_flag("--no-cache", nocache)
        command_builder.add_flag("--progress", self._progress)
        command_builder.add_flag("--pull", pull)
        command_builder.add_arg("--tag", tag)
        command_builder.add_arg("--target", target)
        command_builder.add_arg("--iidfile", iidfile)
        args = command_builder.build([path])
        if self.quiet:
            with subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            ) as p:
                stdout, stderr = p.communicate()
                if p.wait() != 0:
                    # TODO: add better error handling
                    print(f"error building image: {dockerfile}")
                    print("------- STDOUT ---------")
                    print(stdout, end="")
                    print("----------------")
                    print()
                    print("------- STDERR ---------")
                    print(stderr, end="")
                    print("----------------")
        else:
            with subprocess.Popen(args, stdout = sys.stderr.buffer, universal_newlines=True) as p:
                if p.wait() != 0:
                    print("TODO: error building image")

        with open(iidfile) as f:
            line = f.readline()
            image_id = line.split(":")[1].strip()
        os.remove(iidfile)
        return image_id


class _CommandBuilder(object):
    def __init__(self):
        self._args = ["docker", "build"]

    def add_arg(self, name, value):
        if value:
            self._args.extend([name, str(value)])

    def add_flag(self, name, flag):
        if flag:
            self._args.extend([name])

    def add_params(self, name, params):
        if params:
            for key, val in params.items():
                self._args.extend([name, "{}={}".format(key, val)])

    def add_list(self, name, values):
        if values:
            for val in values:
                self._args.extend([name, val])

    def build(self, args):
        return self._args + args


# example of a mutator
def waf_mutator(image: Image, appsec_rule_version: str):
    return image.modify_image(
        append_paths_mapped={
            "SYSTEM_TESTS_APPSEC_EVENT_RULES_VERSION": VirtualFile(appsec_rule_version),
            "waf_rule_set.json": "binaries/waf_rule_set.json",
        },
        env={
            "DD_APPSEC_RULES": "/waf_rule_set.json",
            "DD_APPSEC_RULESET": "/waf_rule_set.json",
            "DD_APPSEC_RULES_PATH": "/waf_rule_set.json",
        },
    )


def _cli_locate_image(ptr):
    if Path(ptr).exists():
        return Dockerfile(Path(ptr)).image()

    dockerfile: Dockerfile = locate(ptr)
    if dockerfile:
        return dockerfile.image()

    return Image(ptr)


def _cli_build_image(args):
    image = _cli_locate_image(args.image)
    print(image.iid)


def _cli_waf_mutator(args):
    image = _cli_locate_image(args.image)
    mutated_image = waf_mutator(image, args.waf_rule_version)
    print(mutated_image.iid)


def _cli_cat_file(args):
    image = _cli_locate_image(args.image)
    print(image.read_file_str(args.path), end = None)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="utils.docker", description="system-tests docker utility"
    )
    subparsers = parser.add_subparsers()
    build_parser = subparsers.add_parser("build")
    build_parser.set_defaults(func=_cli_build_image)
    image_help = (
        "python resource path to Dockerfile object e.g. utils.build.docker.golang.net-http a dockerfile path, or a docker image identifier e.g. busybox or 18fa1f67c0a3b52e50d9845262a4226a6e4474b80354c5ef71ef27e438c6650b ",
    )

    build_parser.add_argument("image", help=image_help)

    waf_mutator_parser = subparsers.add_parser("waf_mutate")
    waf_mutator_parser.set_defaults(func=_cli_waf_mutator)
    waf_mutator_parser.add_argument("image", help=image_help)
    waf_mutator_parser.add_argument("waf_rule_version", help="waf rule version")

    extract_files_parser = subparsers.add_parser("cat_file")
    extract_files_parser.set_defaults(func=_cli_cat_file)
    extract_files_parser.add_argument("image", help=image_help)

    extract_files_parser.add_argument("path")

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)

{
  description = "docker-builder";
  nixConfig.bash-prompt-prefix = "\[d-b\] ";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    treefmt-nix.url = "github:numtide/treefmt-nix";

    pyproject-nix.url = "github:nix-community/pyproject.nix";
    # flake-root.url = "github:srid/flake-root";
  };

  outputs =
    { self
    , nixpkgs
    , flake-utils
    , treefmt-nix
    , pyproject-nix
    ,
    }:
    flake-utils.lib.eachDefaultSystem (system:
    let
      project = pyproject-nix.lib.project.loadPyproject {
        projectRoot = ./.;
      };
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python310;

      projectAttrs = project.renderers.buildPythonPackage { inherit python; };

      projectPythonDeps = project.renderers.withPackages { inherit python; };

      pythonEnv = python.withPackages projectPythonDeps;


      pythonPackages = pkgs.python310Packages;
      treefmt = treefmt-nix.lib.evalModule pkgs ./treefmt.nix;

      projectLib = python.pkgs.buildPythonPackage (projectAttrs);
    in
    {
      packages = {
        python = python;
      };

      packages.default = projectLib;

      formatter = treefmt.config.build.wrapper;
      devShells.default =
        pkgs.mkShell
          {
            venvDir = "./.venv";
            packages =
              [
                pythonEnv
                pythonPackages.pytest
                pythonPackages.venvShellHook
              ];
            postShellHook = ''
              export PYTHONPATH="$PYTHONPATH:$(pwd)" # ensuring pytest invocation works
            '';
          };
    });
}

{
  description = "KTG";
  nixConfig.bash-prompt-prefix = "\[ktg\] ";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    treefmt-nix.url = "github:numtide/treefmt-nix";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    treefmt-nix,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python310;
      pythonPackages = pkgs.python310Packages;
      treefmt = treefmt-nix.lib.evalModule pkgs ./treefmt.nix;
      devtools = pkgs.symlinkJoin {
        name = "devtools";
        paths = [
          python
          pkgs.curl
        ];
        postBuild = "echo links added";
      };
    in {
      packages = {
        python = python;
        default = python;
        devtools = devtools;
      };
      formatter = treefmt.config.build.wrapper;
      devShells.default =
        pkgs.mkShell
        {
          venvDir = "./.venv";
          packages =
            [
              devtools
            ]
            ++ (with pythonPackages; [six setuptools wheel venvShellHook]);
        };
    });
}

# Hashes below are for the pinned v1.36.2+k3s1 release.
{ pkgs, version }:
let
  artifacts = {
    aarch64-linux = {
      file = "k3s-arm64";
      hash = "sha256-HcX8F/FcKPoKPwEc7iitYT+RjD2WekJuWgXUPdsjmBc=";
    };
    x86_64-linux = {
      file = "k3s";
      hash = "sha256-ZaVexWwk6rRDgwhhZuxiCkkZUrfiOUGkndym6KTEtN4=";
    };
  };
  artifact =
    artifacts.${pkgs.stdenv.hostPlatform.system}
      or (throw "unsupported K3s platform: ${pkgs.stdenv.hostPlatform.system}");
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "k3s";
  inherit version;
  src = pkgs.fetchurl {
    url = "https://github.com/k3s-io/k3s/releases/download/v${version}/${artifact.file}";
    inherit (artifact) hash;
  };
  dontUnpack = true;
  installPhase = ''
    install -D -m 0755 "$src" "$out/bin/k3s"
  '';
}

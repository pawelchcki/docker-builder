#!/bin/bash
docker run -it -v /var/run/docker.sock:/var/run/docker.sock -v $(pwd):/workdir ghcr.io/pawelchcki/docker-builder:latest docker-builder "$@"


# WIP usage:
# docker buildx build . -f dist.Dockerfile  -t ghcr.io/pawelchcki/docker-builder:latest --load
# ./exec.sh build /workdir/tests/basic.Dockerfile

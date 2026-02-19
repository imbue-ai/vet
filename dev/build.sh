#!/bin/bash

INSTALL_CLAUDE=false
IMAGE_NAME="vet"

if [ "$1" = "claude" ]; then
    INSTALL_CLAUDE=true
    IMAGE_NAME="vet-claude"
fi

sudo docker build \
    --build-arg INSTALL_CLAUDE=$INSTALL_CLAUDE \
    -t $IMAGE_NAME \
    dev/.

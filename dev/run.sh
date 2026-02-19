#!/bin/bash
sudo docker run -it \
    --mount type=bind,source="$(pwd)",target=/app \
    vet:latest sh 

#!/bin/bash

if [ "$TRAVIS_BRANCH" == "develop" ]; then
    python build/build.py \
    	--username "$USERNAME" \
    	--bcbiovm-branch "$TRAVIS_BRANCH" \
    	--bcbio-branch "$BCBIO_BRANCH" \
    	--upload --token "$BINSTAR_TOKEN" \
    	--numpy "$NUMPY";
else
    python build/build.py \
    	--username "$USERNAME" \
    	--bcbio-branch "$BCBIO_BRANCH" \
    	--bcbiovm-branch "$TRAVIS_BRANCH" \
    	--numpy "$NUMPY";
fi

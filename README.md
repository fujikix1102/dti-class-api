# DTI CLASS API

External exploratory compute backend for DTI-Core Grand Auditor.

## Boundary

This API is exploratory and non-canonical.

It is not:
- a likelihood evaluation
- a posterior comparison
- a Planck validation pipeline
- a manuscript checkpoint updater

## Endpoints

- GET /health
- POST /class/compute

## Local run

    pip install -r requirements.txt
    bash run_local.sh

Optional CLASS/PyCLASS:

    pip install -r requirements-classy.txt

## Test

    bash test_api.sh http://127.0.0.1:8000

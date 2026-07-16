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

## Render deployment

This repository includes:

- `Dockerfile`
- `render.yaml`

Recommended Render settings:

- Service type: Web Service
- Environment: Docker
- Repository: `fujikix1102/dti-class-api`
- Branch: `main`
- Health check path: `/health`
- Start command: handled by Dockerfile

After deployment, check:

    https://YOUR-RENDER-URL/health

Expected response includes:

    "status": "ok"

If `classy_available` is `true`, CLASS/PyCLASS is available on the deployed backend.
If `classy_available` is `false`, the API still works as a safe wrapper but does not run CLASS propagation.

## Streamlit frontend connection

The Streamlit frontend should later call:

    POST https://YOUR-RENDER-URL/class/compute

Boundary:

- exploratory backend
- non-canonical
- not a likelihood evaluation
- not a posterior comparison
- not a Planck validation pipeline

## AxiCLASS + Cobaya DESI DR2 BAO endpoint

Bounded endpoints:

- `GET /axiclass/desi-dr2-bao/health`
- `GET /axiclass/desi-dr2-bao/provenance`
- `POST /axiclass/desi-dr2-bao`

The POST endpoint currently accepts only the locked Planck-2018-baseline-like
parameter contract. It executes the pinned Linux AxiCLASS build through a
Cobaya Theory provider and evaluates the inherited DESI DR2 BAO `theory_fun`
and `logp` methods using explicitly bound frozen mean and covariance files.

Boundaries:

- no sampler;
- no posterior;
- no MCMC;
- no historical-chain reproduction;
- no normalized likelihood claim;
- no EDE-branch claim;
- no reuse of 30.06.

# plane-cow on dev GKE — throwaway install

Minimal install of Plane (CE Helm chart) onto the `dev` GKE cluster
(`gke_trail-ml-9e15e_europe-west1-c_trail-dev`) for manual testing of the cow
agent. **Not** production: postgres/redis/rabbitmq/minio all run in-cluster with
default credentials and small ephemeral volumes. Tear down by deleting the
namespace.

## Prereqs

- `kubectl` context = `dev`
- `helm` 3.x
- `docker` with `buildx` (and `gcloud auth configure-docker europe-west1-docker.pkg.dev` already done)

## Build & push the custom api image

The cow agent code lives in `apps/api/plane/cow/` and ships inside the api
image, which is reused by the worker, beat-worker, and migrator workloads.

```bash
./deployments/k8s-dev/build-and-push.sh
```

Pushes `europe-west1-docker.pkg.dev/trail-ml-9e15e/cow-gym-testing/plane-cow-api`
with tags `:v1.2.3` (consumed by the chart), `:<git-sha>`, and `:latest`.

Re-run after any change under `apps/api/`.

## Install

```bash
helm repo add makeplane https://helm.plane.so/
helm repo update

helm upgrade --install plane-cow makeplane/plane-ce \
  --create-namespace \
  --namespace plane-cow \
  -f deployments/k8s-dev/values.yaml \
  --timeout 10m \
  --wait --wait-for-jobs

# Path-based router (Caddy) that fronts web/api/live/admin/space/minio on a
# single port — replaces what apps/proxy/ does in docker-compose. Without it
# the SPA's POSTs to /auth/* and /api/* hit the frontend's static nginx and
# return 405.
kubectl apply -f deployments/k8s-dev/proxy.yaml
kubectl -n plane-cow rollout status deploy/plane-cow-proxy

# Expose the drf-spectacular OpenAPI spec at /api/schema/ so external clients
# (e.g. cow_gym route discovery) can ingest it. The plane-ce chart ships an
# app-vars ConfigMap with no pass-through for arbitrary env, so patch it and
# roll the workloads that read it.
kubectl -n plane-cow patch configmap plane-cow-app-vars \
  --type=merge -p='{"data":{"ENABLE_DRF_SPECTACULAR":"1"}}'
kubectl -n plane-cow rollout restart \
  deploy/plane-cow-api-wl deploy/plane-cow-worker-wl deploy/plane-cow-beat-worker-wl
```

The migrator runs as a Job and must complete before the api Deployment becomes
ready — `--wait-for-jobs` covers this.

## Access

Ingress is disabled. Port-forward the in-cluster Caddy proxy:

```bash
kubectl -n plane-cow port-forward svc/plane-cow-proxy 38080:80
# then open http://localhost:38080
```

## Pointing the agent at it

The cow agent is wired into the api image and toggled by `ENABLE_COW=1`
(default in `apps/api/.env.example`). For agent test runs that hit this
deployment, point the agent at the port-forwarded web URL above and create a
workspace through the normal sign-up flow on first boot.

## In-cluster clients (e.g. cow_gym)

For pods in another namespace, target the Caddy proxy — it owns a real
ClusterIP and routes `/api/*` to the api workload, so the same base URL works
for both schema discovery and runtime calls:

```
http://plane-cow-proxy.plane-cow.svc.cluster.local
```

OpenAPI spec lives at `/api/schema/` (drf-spectacular YAML, ~500 KB). PAT auth
goes in the `X-Api-Key` header.

## Teardown

```bash
helm uninstall plane-cow -n plane-cow
kubectl delete pvc -n plane-cow --all   # blow away postgres/redis/minio data
kubectl delete ns plane-cow
```

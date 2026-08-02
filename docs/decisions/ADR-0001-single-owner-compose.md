# ADR-0001: Use a single-owner Docker Compose deployment

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

Personal Execution OS stores sensitive personal records and is intended to be
useful without a hosted account service. The public preview needs one
repeatable installation path that includes the web client, API, worker,
database, queue, migrations, health checks, and private persistent volumes.
It does not yet have the support, security assessment, recovery tooling, or
administrative model required for a managed multi-user service.

## Decision drivers

- Give one operator direct control of the host, data, credentials, and updates.
- Make a clean installation reproducible across supported development hosts.
- Keep database and queue ports off the host network.
- Generate private configuration without requiring a hosted control plane.
- Avoid claiming multi-user or hardened public-internet support.

## Considered options

1. Operate a hosted multi-user SaaS product.
2. Ship host-native installers and ask users to install every dependency.
3. Publish a Kubernetes or cloud-platform deployment.
4. Support one local owner through a Docker Compose stack.

## Decision

The supported deployment is a single-owner Docker Compose stack. It runs
PostgreSQL, Redis, a one-shot migration process, FastAPI, an ARQ worker, and an
unprivileged NGINX web edge. The web port binds to `127.0.0.1` by default.
Remote access is an operator-owned extension requiring TLS, exact host and
origin configuration, firewalling, and completed first-run setup.

This choice defines the supported deployment. Docker Compose does not turn the
software into a hardened appliance.

## Consequences

### Positive

- One command can construct and health-check a consistent local stack.
- The operator owns the database volumes, secrets, provider credentials, and
  upgrade timing.
- Internal services have no published host ports.
- Containers, dependency versions, startup ordering, and runtime restrictions
  are reviewable in one repository.

### Negative

- Docker is a substantial prerequisite for a personal application.
- The project does not provide hosted synchronization, managed backups,
  account recovery, or automatic upgrades.
- Remote phone access requires networking and TLS expertise outside the stack.
- One owner and one installation remain a deliberate product limitation.

### Neutral

- The schema retains account-scoped concepts even though the supported runtime
  maps the local owner to one account.
- Operators may place another access layer in front of the web edge, but that
  layer is not supplied or certified here.

## Security, privacy, and operations

The `edge` and internal `data` networks reduce accidental reachability. NGINX
cannot join the database network, and data services do not have host ports.
The worker uses a separate `worker-egress` network, while the API uses its
`edge` network. This separates connectivity but does not provide an outbound
provider allowlist. The API and worker can still contact arbitrary Internet
destinations available through the host.

The localhost binding is a safe default, not authentication or TLS. Exposing an
uninitialized instance can allow another person to claim its one-time setup
flow. Backups, host patching, disk encryption, remote access, and provider
accounts remain operator responsibilities.

## Verification in code and tests

- [`compose.yml`](../../compose.yml) defines the supported services, networks,
  volumes, localhost port binding, health checks, and container restrictions.
- [`scripts/start.sh`](../../scripts/start.sh) creates private configuration,
  generates secrets, starts migrations, and waits for health.
- [`docker/nginx-site.conf.template`](../../docker/nginx-site.conf.template)
  implements the same-origin edge and exact-host behavior.
- [`tests/unit/test_self_hosted_compose.py`](../../tests/unit/test_self_hosted_compose.py)
  checks the topology, localhost binding, startup ordering, identity-file
  handling, restrictions, and host-header behavior.

## Revisit when

- A maintained hosted or multi-user product becomes an explicit goal.
- Native installers can provide equal reproducibility and isolation.
- The project supports a tested public-cloud deployment and incident model.
- Real operator evidence shows Docker is the dominant adoption barrier.

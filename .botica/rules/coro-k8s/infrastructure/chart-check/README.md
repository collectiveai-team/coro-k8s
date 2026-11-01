## Directive

`prek.toml` has a hook with the id `chart-check`, so that the coro chart passes `helm lint
--strict` and every manifest it renders passes kubeconform, for each values file under
`charts/coro/ci/`, before a change to the chart is committed and on every CI run.

## Why

A template renders text, and Helm checks only that the text is YAML. A field name with a typo, a
value of the wrong type or a field that the API version does not have still renders, and the API
server rejects it at install time, or, for a field inside an object it does not prune, silently
drops it. Each values file of `ci/` turns on a different set of templates (GPU, KEDA and
ServiceMonitor, HPA), so a template that only one of them renders is still checked.

## Exceptions

A checkout without `charts/coro/Chart.yaml` has no chart. `external-config` skips the rule unless
that file exists.

## Tool

[helm lint](https://helm.sh/docs/helm/helm_lint/) renders the chart and reports template errors
and the `fail` calls of `coro.validate`. [kubeconform](https://github.com/yannh/kubeconform)
validates the rendered manifests with `-strict` against the JSON schemas of the Kubernetes version
given to `scripts/check-chart.sh`, and the CRDs against the datreeio CRDs catalog.
kubeconform runs from its image, pinned by version and digest; helm comes from `PATH` (the CI
installs it with `azure/setup-helm`).

## Configuration

The hook in `prek.toml`, as `config/prek.toml` of this rule holds it. `external-config` checks that
a hook with the id `chart-check` is there.

## Do

```yaml
securityContext:
  allowPrivilegeEscalation: false
```

## Don't

```yaml
securityContext:
  allowPriviledgeEscalation: false
```

kubeconform reports `additional properties 'allowPriviledgeEscalation' not allowed`.

## Suppression

Neither tool has a suppression for one finding. Fix the template, or add a values file under
`ci/` only when it describes a configuration the chart supports.

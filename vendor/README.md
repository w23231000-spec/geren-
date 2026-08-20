# Bundled modules

- `hfss_builder`: audited copy of `PA_MULTI_9parametric_builder` supplied by the user.
- `optimizer`: audited copy of the geometry-constrained optimizer including its S-parameter surrogate.

The Agent accesses these copies through Interface/Adapter boundaries. The original archives are not modified at runtime.

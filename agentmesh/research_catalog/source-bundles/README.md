# Gate 0 source bundle

This directory contains an evidence-only, deterministic Git bundle. It has no `__init__.py`, is not
listed in `tool.setuptools.package-data`, and is never searched by runtime catalog or Skill loaders.
The Gate verifier opens the bundle only through its explicit committed evidence path.

The bundle advertises only `refs/heads/parity` at synthetic orphan snapshot commit
`adf97f60f46ecceae5a2bc7f3d8c232484c334bd`. That commit's tree is
`ca63e2fdb4c3fcff0f50c8095a1497f8db4cdd12`, exactly equal to reviewed source commit
`d7ec877fbff0684b0886cb86a7e09eb42ebf7d77`'s tree. Source history is intentionally absent. The
adjacent attestation records origin, deterministic construction, restore, strict fsck, reachable-object
minimality, and all-blob/PDF scan evidence.

Do not import, execute, unpack, or serve these files from production runtime code.

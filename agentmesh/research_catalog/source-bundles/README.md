# Gate 0 source bundles

This directory contains evidence-only Git bundles. It has no `__init__.py`, is not listed in
`tool.setuptools.package-data`, and is never searched by runtime catalog or Skill loaders. The Gate
verifier opens a bundle only through its explicit evidence path. Do not import, execute, unpack, or
serve these files from production runtime code.

# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.17.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# # Example Notebook for zenodo-release-drift

from zenodo_release_drift import lint_repo

# Detect drift for a repository (replace with a real owner/repo)
findings = lint_repo("example-owner", "example-repo")
print(findings)

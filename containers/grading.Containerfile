# Grading sandbox: runs model-authored code with no network and no credentials.
#
# Base pinned by digest. A floating tag means two runs of the same commit can
# use different tools while reporting the same configuration.
#
# NOT alpine: busybox find has no -printf, which the container-manifest check
# in harness/fixture.py depends on.
FROM docker.io/library/python@sha256:16f75ad0fbc6c4883a8afd63b2d700c3cf68ccffc1aaeca5304ca0a3a908451f

RUN pip install --no-cache-dir \
      "django==5.2.7" \
      "djangorestframework==3.16.1" \
      "pytest==8.4.2" \
      "pytest-django==4.11.1" \
      "pytest-json-report==1.5.0" \
      "tzdata==2025.2"

WORKDIR /workspace

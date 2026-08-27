# Agent sandbox: where the model under test actually runs.
#
# This container is not merely a hardening layer. Spec 6.0: an isolated HOME is
# the only mechanism that produces a sterile opencode configuration, so running
# the agent on the host would silently execute against the operator's personal
# global config.
FROM docker.io/library/python@sha256:16f75ad0fbc6c4883a8afd63b2d700c3cf68ccffc1aaeca5304ca0a3a908451f

ARG OPENCODE_VERSION=1.18.23
# Checksum of https://opencode.ai/install as fetched 2026-08-27. The URL is
# mutable, so this pin exists to make an upstream change VISIBLE. If the build
# fails here, review the new installer - do not bump the hash reflexively.
ARG OPENCODE_INSTALLER_SHA256=fc3c1b2123f49b6df545a7622e5127d21cd794b15134fc3b66e1ca49f7fb297e

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip tar git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/oc-install.sh https://opencode.ai/install \
    && echo "${OPENCODE_INSTALLER_SHA256}  /tmp/oc-install.sh" | sha256sum -c - \
    && VERSION="${OPENCODE_VERSION}" bash /tmp/oc-install.sh \
    && rm -f /tmp/oc-install.sh

ENV PATH="/root/.opencode/bin:${PATH}"

# The fixture stack, so the agent can actually run the tests it is asked to run.
RUN pip install --no-cache-dir \
      "django==5.2.7" \
      "djangorestframework==3.16.1" \
      "pytest==8.4.2" \
      "pytest-django==4.11.1" \
      "tzdata==2025.2"

WORKDIR /workspace

# The digest pins LibreLane and its complete Nix-built EDA tool closure.
ARG LIBRELANE_IMAGE=ghcr.io/librelane/librelane:3.0.16@sha256:02d50f259d483979e126ef188a50f5b61e1d285b9d538312f280b087439b0302
FROM ${LIBRELANE_IMAGE}

ADD --checksum=sha256:fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70 https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl /tmp/pip.whl

# Linux arm64 has no cocotb wheel. Reuse the pinned compiler in the EDA closure.
RUN python3 -c 'import zipfile; zipfile.ZipFile("/tmp/pip.whl").extractall("/tmp/pip")' && \
    export PATH="$(find /nix/store -maxdepth 1 -name '*-gcc-wrapper-*' | head -1)/bin:$PATH" && \
    export PYTHONPATH="/tmp/pip:$(find /nix/store -path '*-python3.13-setuptools-*/lib/python3.13/site-packages' | head -1):$(find /nix/store -path '*-python3.13-wheel-*/lib/python3.13/site-packages' | head -1):$(find /nix/store -path '*-python3.13-packaging-*/lib/python3.13/site-packages' | head -1)" && \
    python3 -m pip install --target /opt/silicon-python --no-cache-dir --no-build-isolation cocotb==2.0.1 find_libpython==0.5.1 && \
    rm -rf /tmp/pip /tmp/pip.whl

ENV PYTHONPATH=/opt/silicon-python
ENV NIX_PYTHONPATH=/opt/silicon-python:${NIX_PYTHONPATH}
ENV PATH=/opt/silicon-python/bin:${PATH}
ENV QT_QPA_PLATFORM=offscreen
WORKDIR /work
